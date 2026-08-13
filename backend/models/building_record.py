from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base

if TYPE_CHECKING:
    from models.landowner import Landowner


class BuildingRecord(Base):
    __tablename__ = "building_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    landowner_id: Mapped[int | None] = mapped_column(ForeignKey("landowners.id", ondelete="SET NULL"), nullable=True)
    land_record_id: Mapped[int | None] = mapped_column(ForeignKey("land_records.id", ondelete="SET NULL"), nullable=True)
    building_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    floor: Mapped[str | None] = mapped_column(String(20), nullable=True)
    total_floors: Mapped[str | None] = mapped_column(String(50), nullable=True)
    registration_order: Mapped[str | None] = mapped_column(String(50), nullable=True)
    structure_area_sqm: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    auxiliary_area_sqm: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    common_area_sqm: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    # Computed by application code at write time (not a SQL GENERATED column).
    total_area_sqm: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    ownership_numerator: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    ownership_denominator: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    ownership_share_pct: Mapped[float] = mapped_column(Numeric(9, 6), nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    landowner: Mapped["Landowner"] = relationship(back_populates="building_records")
