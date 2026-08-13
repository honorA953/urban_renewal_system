from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class Encumbrance(Base):
    __tablename__ = "encumbrances"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    applies_to_parcels: Mapped[str | None] = mapped_column(String(255), nullable=True)
    registration_order: Mapped[str | None] = mapped_column(String(50), nullable=True)
    right_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    right_holder: Mapped[str | None] = mapped_column(String(255), nullable=True)
    debtor_info: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
