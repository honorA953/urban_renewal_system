import base64
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_db
from deps import require_staff_or_admin
from models.document import Document
from models.ocr import OcrJob, OcrMatchResult
from models.ocr_job_document import OcrJobDocument
from models.user import User
from routers.projects import get_project_or_404
from schemas.ocr import OcrExtractionResult, OcrJobRead, PagePreview, PageSplitResult, TitleDeedExtraction
from utils.file_storage import build_upload_path
from utils.ocr import OcrError, _flatten_to_pages, detect_page_groups, extract_title_deed

router = APIRouter(prefix="/projects/{project_id}", tags=["ocr"])


@router.get("/ocr-jobs", response_model=list[OcrJobRead])
def list_ocr_jobs(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff_or_admin),
):
    get_project_or_404(db, project_id)
    return db.scalars(select(OcrJob).where(OcrJob.project_id == project_id).order_by(OcrJob.created_at.desc())).all()


@router.post("/ocr/split-pages", response_model=PageSplitResult)
def split_pages_for_grouping(
    project_id: int,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff_or_admin),
):
    """Splits any uploaded PDFs into per-page images (reusing the same logic the OCR
    call itself uses) and returns them as previews, without persisting anything. Also
    suggests a group number per page based on the 「續次頁」(continued on next page)
    marker printed at the bottom of each page, so the wizard's grouping step starts
    from a reasonable auto-detected grouping instead of everything defaulting to one
    group - the user can still review and override every page before OCR runs."""
    get_project_or_404(db, project_id)
    file_payload = [(upload.file.read(), upload.content_type) for upload in files]
    try:
        pages = _flatten_to_pages(file_payload)
    except OcrError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    groups, warning = detect_page_groups(pages)
    previews = [
        PagePreview(
            page_number=i + 1,
            image_base64=base64.b64encode(content).decode("ascii"),
            mime_type=mime_type or "image/png",
            suggested_group=groups[i],
        )
        for i, (content, mime_type) in enumerate(pages)
    ]
    return PageSplitResult(pages=previews, warning=warning)


@router.post("/ocr/title-deed", response_model=OcrExtractionResult, status_code=status.HTTP_201_CREATED)
def extract_title_deed_job(
    project_id: int,
    files: list[UploadFile] = File(...),
    record_type: str = Form("both"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff_or_admin),
):
    """Runs structured extraction on 1+ scanned pages of a title deed (images or PDFs,
    in the given order), synchronously via OpenAI. Every uploaded page is also saved as
    a project document for traceability. record_type ("land"/"building"/"both") tells the
    model which section(s) this batch actually contains, so e.g. a land-only upload
    doesn't get a spurious buildings entry conjured out of land-page content (or vice
    versa) - the frontend lets the user declare this upfront since they always know
    which kind of deed they're uploading. The result is a best-effort suggestion for the
    frontend's step-by-step review wizard."""
    if record_type not in ("land", "building", "both"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid record_type")
    project = get_project_or_404(db, project_id)

    job = OcrJob(project_id=project_id, status="processing", job_type="title_deed")
    job.started_at = datetime.now(timezone.utc)
    db.add(job)
    db.flush()

    documents: list[Document] = []
    for upload in files:
        content = upload.file.read()
        disk_path, stored_name = build_upload_path(project.project_code, upload.filename or "upload")
        with open(disk_path, "wb") as out:
            out.write(content)
        document = Document(
            project_id=project_id,
            doc_type="property_register",
            file_name=upload.filename or stored_name,
            file_path=disk_path,
            file_size_bytes=len(content),
            mime_type=upload.content_type,
            uploaded_by=current_user.id,
            description="謄本掃描匯入",
        )
        db.add(document)
        db.flush()
        documents.append(document)
        db.add(OcrJobDocument(ocr_job_id=job.id, document_id=document.id, page_order=len(documents) - 1))

    try:
        file_payload = []
        for doc in documents:
            with open(doc.file_path, "rb") as f:
                file_payload.append((f.read(), doc.mime_type))
        parsed, warning = extract_title_deed(file_payload, record_type=record_type)
    except (OcrError, OSError) as exc:
        job.status = "failed"
        job.error_message = str(exc)
        job.completed_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(job)
        return OcrExtractionResult(job=OcrJobRead.model_validate(job), data=None)

    match = OcrMatchResult(ocr_job_id=job.id, extracted_data=parsed)
    db.add(match)

    # Rename/relabel the documents this call just saved to reflect what was actually
    # found on them (地號/建號), instead of leaving them as generic "謄本掃描匯入" -
    # this only produces one clean label per call because the wizard's manual-grouping
    # flow sends one 地號/建號's pages per call; a single ungrouped batch covering
    # several parcels/buildings still gets labeled, just with all of them joined.
    labels = [f"地號{p['parcel_number']}" for p in parsed["land_parcels"] if p.get("parcel_number")]
    labels += [f"建號{b['building_number']}" for b in parsed["buildings"] if b.get("building_number")]
    labels = list(dict.fromkeys(labels))  # de-dupe while preserving order, in case extraction ever repeats a parcel/building
    if labels:
        archive_label = "、".join(labels)
        for i, doc in enumerate(documents):
            ext = os.path.splitext(doc.file_name or "")[1] or ".png"
            doc.description = f"謄本掃描匯入 - {archive_label}"
            doc.file_name = f"{archive_label}_第{i + 1}頁{ext}" if len(documents) > 1 else f"{archive_label}{ext}"

    # Still "completed" - some pages were successfully extracted - but error_message
    # carries a non-fatal warning when part of a multi-chunk batch failed, so the
    # frontend can tell the user the result may be incomplete instead of silently
    # under-reporting parcels/buildings.
    job.status = "completed"
    job.error_message = warning
    job.completed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(job)

    return OcrExtractionResult(job=OcrJobRead.model_validate(job), data=TitleDeedExtraction(**parsed))
