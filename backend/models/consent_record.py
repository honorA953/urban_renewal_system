from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class ConsentRecord(Base):
    __tablename__ = "consent_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    landowner_id: Mapped[int] = mapped_column(ForeignKey("landowners.id", ondelete="CASCADE"), nullable=False)
    sop_stage: Mapped[int] = mapped_column(Integer, nullable=False)
    consent_status: Mapped[str] = mapped_column(String(10), nullable=False, default="pending")
    recorded_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    recorded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
