import base64

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from deps import require_staff_or_admin
from models.user import User
from schemas.ocr import CaseDetectResult, CasePagePreview
from utils.ocr import OcrError, _flatten_to_pages, detect_case_groups

router = APIRouter(prefix="/ocr", tags=["ocr"])


@router.post("/detect-cases", response_model=CaseDetectResult)
def detect_cases_for_batch_import(
    files: list[UploadFile] = File(...),
    current_user: User = Depends(require_staff_or_admin),
):
    """Splits an uploaded batch (images/PDFs) into per-page images and guesses which
    都更案件 (urban renewal case) each page belongs to, by reading the 鄉鎮市區/段/小段
    printed in each page's title. Not scoped to a project - this runs before the user
    has decided which project(s) the batch even belongs to, as the first step of
    batch-importing a mixed pile of scanned title deeds."""
    file_payload = [(upload.file.read(), upload.content_type) for upload in files]
    try:
        pages = _flatten_to_pages(file_payload)
    except OcrError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    groups, warning = detect_case_groups(pages)
    previews = [
        CasePagePreview(
            page_number=i + 1,
            image_base64=base64.b64encode(content).decode("ascii"),
            mime_type=mime_type or "image/png",
            suggested_case_group=groups[i][0],
            case_label=groups[i][1],
            sample_number=groups[i][2],
        )
        for i, (content, mime_type) in enumerate(pages)
    ]
    return CaseDetectResult(pages=previews, warning=warning)
