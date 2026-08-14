from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_db
from deps import require_staff_or_admin
from models.document import Document
from models.ocr import OcrJob, OcrMatchResult
from models.ocr_job_document import OcrJobDocument
from models.user import User
from routers.projects import get_project_or_404
from schemas.ocr import OcrExtractionResult, OcrJobRead, TitleDeedExtraction
from utils.file_storage import build_upload_path
from utils.ocr import OcrError, extract_title_deed

router = APIRouter(prefix="/projects/{project_id}", tags=["ocr"])


@router.get("/ocr-jobs", response_model=list[OcrJobRead])
def list_ocr_jobs(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff_or_admin),
):
    get_project_or_404(db, project_id)
    return db.scalars(select(OcrJob).where(OcrJob.project_id == project_id).order_by(OcrJob.created_at.desc())).all()


@router.post("/ocr/title-deed", response_model=OcrExtractionResult, status_code=status.HTTP_201_CREATED)
def extract_title_deed_job(
    project_id: int,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff_or_admin),
):
    """Runs structured five-section extraction on 1+ scanned pages of a single 土地登記
    謄本 (images or PDFs, in the given order), synchronously via Gemini. Every uploaded
    page is also saved as a project document for traceability. The result is a
    best-effort suggestion for the frontend's step-by-step review wizard."""
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
        parsed, warning = extract_title_deed(file_payload)
    except (OcrError, OSError) as exc:
        job.status = "failed"
        job.error_message = str(exc)
        job.completed_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(job)
        return OcrExtractionResult(job=OcrJobRead.model_validate(job), data=None)

    match = OcrMatchResult(ocr_job_id=job.id, extracted_data=parsed)
    db.add(match)

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
