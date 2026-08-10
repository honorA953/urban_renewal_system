import os

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_db
from deps import get_current_user, require_staff_or_admin
from models.document import Document
from models.user import User
from routers.projects import assert_project_visible, get_project_or_404
from schemas.document import DocumentRead
from utils.file_storage import build_upload_path

router = APIRouter(prefix="/projects/{project_id}/documents", tags=["documents"])

VALID_DOC_TYPES = {"property_register", "consent_form", "briefing_material", "contract", "photo", "other"}


@router.get("", response_model=list[DocumentRead])
def list_documents(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_project_or_404(db, project_id)
    assert_project_visible(db, project, current_user)
    return db.scalars(
        select(Document).where(Document.project_id == project_id).order_by(Document.uploaded_at.desc())
    ).all()


@router.post("", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
def upload_document(
    project_id: int,
    file: UploadFile = File(...),
    doc_type: str = Form("other"),
    landowner_id: int | None = Form(None),
    description: str | None = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff_or_admin),
):
    project = get_project_or_404(db, project_id)

    if doc_type not in VALID_DOC_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid doc_type")

    disk_path, stored_name = build_upload_path(project.project_code, file.filename or "upload")
    content = file.file.read()
    with open(disk_path, "wb") as out:
        out.write(content)

    document = Document(
        project_id=project_id,
        landowner_id=landowner_id,
        doc_type=doc_type,
        file_name=file.filename or stored_name,
        file_path=disk_path,
        file_size_bytes=len(content),
        mime_type=file.content_type,
        uploaded_by=current_user.id,
        description=description,
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


def get_document_or_404(db: Session, project_id: int, doc_id: int) -> Document:
    document = db.scalar(
        select(Document).where(Document.id == doc_id, Document.project_id == project_id)
    )
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return document


@router.get("/{doc_id}/download")
def download_document(
    project_id: int,
    doc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_project_or_404(db, project_id)
    assert_project_visible(db, project, current_user)
    document = get_document_or_404(db, project_id, doc_id)

    if not os.path.exists(document.file_path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File missing on disk")

    return FileResponse(document.file_path, filename=document.file_name, media_type=document.mime_type)


@router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    project_id: int,
    doc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff_or_admin),
):
    document = get_document_or_404(db, project_id, doc_id)

    if os.path.exists(document.file_path):
        os.remove(document.file_path)

    db.delete(document)
    db.commit()
