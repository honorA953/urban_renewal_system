import base64

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from deps import require_staff_or_admin
from models.user import User
from schemas.ocr import CaseDetectResult, CasePagePreview
from utils.ocr import OcrError, _flatten_to_pages, detect_case_groups, downscale_for_preview

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
