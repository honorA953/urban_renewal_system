import base64

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_db
from deps import require_staff_or_admin
from models.project import Project
from models.user import User
from schemas.ocr import BuildingCaseDetectResult, BuildingGroupMatch, CaseDetectResult, CasePagePreview
from utils.ocr import OcrError, _flatten_to_pages, detect_case_groups, downscale_for_preview, extract_title_deed

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
    regex), then - unlike that endpoint - actually runs full OCR/AI extraction on each
    group to read its 建物坐落地號 (the field that says which 地號 the building sits on,
    a different field than the building's own 建號 in the title). Each group is matched
    against existing projects by project_code == 建物坐落地號, so an already-created
    地號 case can be found and filed into automatically; unmatched groups come back with
    matched_project_id=None for the frontend to offer manual selection. This is
    noticeably slower/costlier than /detect-cases: reading 建物坐落地號 needs the model
    to actually parse the page, not just the local OCR+regex header check the case-split
    step uses."""
    file_payload = [(upload.file.read(), upload.content_type) for upload in files]
    try:
        pages = _flatten_to_pages(file_payload)
    except OcrError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    groups, group_warning = detect_case_groups(pages)
    group_numbers = sorted({g[0] for g in groups})
    projects_by_code = {p.project_code: p for p in db.scalars(select(Project)).all()}

    warnings = [group_warning] if group_warning else []
    result_groups: list[BuildingGroupMatch] = []
    for group_number in group_numbers:
        indices = [i for i, g in enumerate(groups) if g[0] == group_number]
        group_pages = [pages[i] for i in indices]

        building_dict: dict | None = None
        try:
            data, extract_warning = extract_title_deed(group_pages, record_type="building")
            if extract_warning:
                warnings.append(f"第{group_number}組:{extract_warning}")
            if data["buildings"]:
                building_dict = data["buildings"][0]
        except OcrError as exc:
            warnings.append(f"第{group_number}組辨識失敗:{exc}")

        if building_dict is not None and not building_dict.get("building_number"):
            building_dict["building_number"] = groups[indices[0]][2]  # fall back to the title's own 建號
        parcel_number = ((building_dict or {}).get("parcel_number") or "").strip()

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
