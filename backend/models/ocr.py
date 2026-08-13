from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class OcrJob(Base):
    """One job = one 謄本, which may span several scanned pages/files (see
    OcrJobDocument for the ordered list of source documents)."""

    __tablename__ = "ocr_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    job_type: Mapped[str] = mapped_column(String(50), nullable=False, default="title_deed")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class OcrMatchResult(Base):
    """The structured five-section extraction (land/building description + ownership +
    encumbrances), stored as JSON since the shape is nested/variable-length - see
    utils/ocr.py RESPONSE_SCHEMA for the exact contract."""

    __tablename__ = "ocr_match_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    ocr_job_id: Mapped[int] = mapped_column(ForeignKey("ocr_jobs.id", ondelete="CASCADE"), nullable=False)
    extracted_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
