from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base

if TYPE_CHECKING:
    from models.landowner import Landowner


class LandRecord(Base):
    __tablename__ = "land_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    landowner_id: Mapped[int | None] = mapped_column(ForeignKey("landowners.id", ondelete="SET NULL"), nullable=True)
    parcel_number: Mapped[str] = mapped_column(String(100), nullable=False)
    township: Mapped[str | None] = mapped_column(String(50), nullable=True)
    section: Mapped[str | None] = mapped_column(String(100), nullable=True)
    subsection: Mapped[str | None] = mapped_column(String(100), nullable=True)
    registration_order: Mapped[str | None] = mapped_column(String(50), nullable=True)
    total_area_sqm: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    ownership_numerator: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    ownership_denominator: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # DB-generated (GENERATED ALWAYS AS ... STORED in schema.sql). Never assign these from
    # application code - MariaDB rejects any explicit value (including NULL) for such columns.
    owned_area_sqm: Mapped[float] = mapped_column(Numeric(14, 4), nullable=True)
    ownership_share_pct: Mapped[float] = mapped_column(Numeric(9, 6), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    landowner: Mapped["Landowner"] = relationship(back_populates="land_records")
