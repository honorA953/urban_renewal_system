from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_db
from deps import require_staff_or_admin
from models.document import Document
from models.ocr import OcrJob, OcrMatchResult
from models.user import User
from routers.projects import get_project_or_404
from schemas.ocr import OcrExtractionResult, OcrJobRead
from utils.ocr import OcrError, extract_land_title_fields

router = APIRouter(prefix="/projects/{project_id}", tags=["ocr"])


@router.get("/ocr-jobs", response_model=list[OcrJobRead])
def list_ocr_jobs(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff_or_admin),
):
    get_project_or_404(db, project_id)
    return db.scalars(select(OcrJob).where(OcrJob.project_id == project_id).order_by(OcrJob.created_at.desc())).all()


@router.post("/documents/{doc_id}/ocr", response_model=OcrExtractionResult, status_code=status.HTTP_201_CREATED)
def start_ocr_job(
    project_id: int,
    doc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff_or_admin),
):
    """Runs field extraction on an uploaded document (a scanned 土地登記謄本 image),
    synchronously via Gemini (Google AI Studio). Extracted fields are suggestions
    only — the frontend pre-fills the 新增地主 form for the user to review."""
    get_project_or_404(db, project_id)
    document = db.scalar(select(Document).where(Document.id == doc_id, Document.project_id == project_id))
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    job = OcrJob(project_id=project_id, document_id=doc_id, status="processing", job_type="land_record")
    job.started_at = datetime.now(timezone.utc)
    db.add(job)
    db.commit()
    db.refresh(job)

    try:
        with open(document.file_path, "rb") as f:
            image_bytes = f.read()
        parsed = extract_land_title_fields(image_bytes, document.mime_type)
    except (OcrError, OSError) as exc:
        job.status = "failed"
        job.error_message = str(exc)
        job.completed_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(job)
        return OcrExtractionResult(job=OcrJobRead.model_validate(job), match=None)

    match = OcrMatchResult(
        ocr_job_id=job.id,
        extracted_name=parsed["name"],
        extracted_id_number=parsed["id_number"],
        extracted_parcel_number=parsed["parcel_number"],
        extracted_section=parsed["section"],
        extracted_address=parsed["address"],
        extracted_total_area_sqm=parsed["total_area_sqm"],
        extracted_ownership_numerator=parsed["ownership_numerator"],
        extracted_ownership_denominator=parsed["ownership_denominator"],
        raw_text=parsed["raw_text"],
    )
    db.add(match)

    job.status = "completed"
    job.completed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(job)
    db.refresh(match)

    return OcrExtractionResult(job=OcrJobRead.model_validate(job), match=match)
