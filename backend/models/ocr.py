from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class OcrJob(Base):
    __tablename__ = "ocr_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    job_type: Mapped[str] = mapped_column(String(50), nullable=False, default="land_record")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class OcrMatchResult(Base):
    __tablename__ = "ocr_match_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    ocr_job_id: Mapped[int] = mapped_column(ForeignKey("ocr_jobs.id", ondelete="CASCADE"), nullable=False)
    extracted_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    extracted_id_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    extracted_parcel_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    extracted_section: Mapped[str | None] = mapped_column(String(100), nullable=True)
    extracted_address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    extracted_total_area_sqm: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    extracted_ownership_numerator: Mapped[int | None] = mapped_column(nullable=True)
    extracted_ownership_denominator: Mapped[int | None] = mapped_column(nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    matched_landowner_id: Mapped[int | None] = mapped_column(ForeignKey("landowners.id", ondelete="SET NULL"), nullable=True)
    confidence_score: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    review_status: Mapped[str] = mapped_column(String(20), nullable=False, default="unreviewed")
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
