import base64

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_db
from deps import require_staff_or_admin
from models.project import Project
from models.user import User
from schemas.ocr import BuildingCaseDetectResult, BuildingGroupMatch, CaseDetectResult, CasePagePreview
from utils.ocr import (
    OcrError,
    _flatten_to_pages,
    detect_building_parcel_numbers,
    detect_case_groups,
    downscale_for_preview,
    extract_title_deed,
)

router = APIRouter(prefix="/ocr", tags=["ocr"])


@router.post("/detect-cases", response_model=CaseDetectResult)
def detect_cases_for_batch_import(
    files: list[UploadFile] = File(...),
    current_user: User = Depends(require_staff_or_admin),
):
    """Splits an uploaded batch (images/PDFs) into per-page images and guesses which
    都更案件 (urban renewal case, one 地號/建號 in this system) each page belongs to, by
    reading the 頁次 field printed in each page's header. Not scoped to a project - this
    runs before the user has decided which project(s) the batch even belongs to, as the
    first step of batch-importing a mixed pile of scanned title deeds."""
    file_payload = [(upload.file.read(), upload.content_type) for upload in files]
    try:
        pages = _flatten_to_pages(file_payload)
    except OcrError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    groups, warning = detect_case_groups(pages)
    # Downscaled for the review grid's benefit only - detect_case_groups() above already
    # ran its own OCR against the full-resolution pages, so shrinking the preview here
    # doesn't affect grouping accuracy. Always JPEG now regardless of the original
    # format, since downscale_for_preview() re-encodes to JPEG.
    previews = [
        CasePagePreview(
            page_number=i + 1,
            image_base64=base64.b64encode(downscale_for_preview(content)).decode("ascii"),
            mime_type="image/jpeg",
            suggested_case_group=groups[i][0],
            case_label=groups[i][1],
            sample_number=groups[i][2],
        )
        for i, (content, mime_type) in enumerate(pages)
    ]
    return CaseDetectResult(pages=previews, warning=warning)


@router.post("/detect-building-cases", response_model=BuildingCaseDetectResult)
def detect_building_cases_for_batch_import(
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff_or_admin),
):
    """Splits an uploaded batch of building deeds into per-建號 groups (same 頁次-based
    grouping as detect_cases_for_batch_import, since both title formats fit the same
    regex), then reads each group's 建物坐落地號 (the field that says which 地號 the
    building sits on, a different field than the building's own 建號 in the title) via a
    second local OCR pass on a taller crop of the group's first page - no OpenAI call, so
    this step stays as fast as /detect-cases. Each group is matched against existing
    projects by project_code == 建物坐落地號, so an already-created 地號 case can be
    found and filed into automatically; unmatched groups come back with
    matched_project_id=None for the frontend to offer manual selection. Full AI
    extraction (owners/address/floors) only happens later, per group, at actual import
    time - see runConfirmBuildingBatchImport in the frontend."""
    file_payload = [(upload.file.read(), upload.content_type) for upload in files]
    try:
        pages = _flatten_to_pages(file_payload)
    except OcrError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    groups, group_warning = detect_case_groups(pages)
    group_numbers = sorted({g[0] for g in groups})
    projects_by_code = {p.project_code: p for p in db.scalars(select(Project)).all()}

    first_page_index_by_group = {gn: next(i for i, g in enumerate(groups) if g[0] == gn) for gn in group_numbers}
    parcel_numbers_by_index = detect_building_parcel_numbers(pages, list(first_page_index_by_group.values()))

    warnings = [group_warning] if group_warning else []
    result_groups: list[BuildingGroupMatch] = []
    for group_number in group_numbers:
        indices = [i for i, g in enumerate(groups) if g[0] == group_number]
        building_number = groups[indices[0]][2]  # from the title's own 建號, read locally
        parcel_number = parcel_numbers_by_index.get(first_page_index_by_group[group_number], "")
        building_dict = {"building_number": building_number, "parcel_number": parcel_number} if building_number or parcel_number else None

        matched = projects_by_code.get(parcel_number) if parcel_number else None
        previews = [
            CasePagePreview(
                page_number=i + 1,
                image_base64=base64.b64encode(downscale_for_preview(pages[i][0])).decode("ascii"),
                mime_type="image/jpeg",
                suggested_case_group=group_number,
                case_label=groups[i][1],
                sample_number=groups[i][2],
            )
            for i in indices
        ]
        result_groups.append(
            BuildingGroupMatch(
                group=group_number,
                pages=previews,
                building=building_dict,
                matched_project_id=matched.id if matched else None,
                matched_project_name=matched.name if matched else "",
                matched_project_code=matched.project_code if matched else "",
            )
        )

    return BuildingCaseDetectResult(groups=result_groups, warning="、".join(warnings) if warnings else None)


@router.post("/extract-building-group")
def extract_building_group(
    files: list[UploadFile] = File(...),
    current_user: User = Depends(require_staff_or_admin),
):
    """Runs full AI extraction on one already-matched building group's pages, called by
    the batch building-import confirm step right before it creates records for that
    group - not scoped to a project, and doesn't save any documents itself (the caller
    separately archives the group's pages as a merged PDF). Kept as its own step, deferred
    until confirm time, so /detect-building-cases above can stay local-OCR-only (fast, no
    API cost) instead of eagerly running AI extraction on every group up front."""
    file_payload = [(upload.file.read(), upload.content_type) for upload in files]
    try:
        pages = _flatten_to_pages(file_payload)
    except OcrError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    try:
        data, warning = extract_title_deed(pages, record_type="building")
    except OcrError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return {"building": data["buildings"][0] if data["buildings"] else None, "warning": warning}
