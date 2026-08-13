from sqlalchemy import ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class OcrJobDocument(Base):
    __tablename__ = "ocr_job_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    ocr_job_id: Mapped[int] = mapped_column(ForeignKey("ocr_jobs.id", ondelete="CASCADE"), nullable=False)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    page_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
