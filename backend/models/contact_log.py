from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class ContactLog(Base):
    __tablename__ = "contact_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    landowner_id: Mapped[int] = mapped_column(ForeignKey("landowners.id", ondelete="CASCADE"), nullable=False)
    contact_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    contact_method: Mapped[str] = mapped_column(String(20), nullable=False, default="phone")
    contact_result: Mapped[str] = mapped_column(String(20), nullable=False, default="undecided")
    staff_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_follow_up_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
