from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_db
from deps import require_staff_or_admin
from models.document import Document
from models.ocr import OcrJob
from models.user import User
from routers.projects import get_project_or_404
from schemas.ocr import OcrJobRead

router = APIRouter(prefix="/projects/{project_id}", tags=["ocr"])


@router.get("/ocr-jobs", response_model=list[OcrJobRead])
def list_ocr_jobs(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff_or_admin),
):
    get_project_or_404(db, project_id)
    return db.scalars(select(OcrJob).where(OcrJob.project_id == project_id).order_by(OcrJob.created_at.desc())).all()


@router.post("/documents/{doc_id}/ocr", response_model=OcrJobRead, status_code=status.HTTP_201_CREATED)
def start_ocr_job(
    project_id: int,
    doc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff_or_admin),
):
    """Stub: registers an OCR job as pending. Actual text extraction is not implemented in v1."""
    get_project_or_404(db, project_id)
    document = db.scalar(select(Document).where(Document.id == doc_id, Document.project_id == project_id))
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    job = OcrJob(project_id=project_id, document_id=doc_id, status="pending", job_type="land_record")
    db.add(job)
    db.commit()
    db.refresh(job)
    return job
