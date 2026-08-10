from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models.consent_record import ConsentRecord
from models.land_record import LandRecord
from models.landowner import Landowner


def calculate_consent_ratio(db: Session, project_id: int, stage: int, threshold: float = 0.8) -> dict:
    headcount_total = db.scalar(
        select(func.count(Landowner.id)).where(Landowner.project_id == project_id)
    ) or 0

    headcount_agreed = db.scalar(
        select(func.count(func.distinct(ConsentRecord.landowner_id)))
        .where(
            ConsentRecord.project_id == project_id,
            ConsentRecord.sop_stage == stage,
            ConsentRecord.consent_status == "agreed",
        )
    ) or 0

    land_share_total_sqm = float(
        db.scalar(
            select(func.coalesce(func.sum(LandRecord.owned_area_sqm), 0)).where(
                LandRecord.project_id == project_id
            )
        )
        or 0
    )

    land_share_agreed_sqm = float(
        db.scalar(
            select(func.coalesce(func.sum(LandRecord.owned_area_sqm), 0))
            .join(Landowner, LandRecord.landowner_id == Landowner.id)
            .join(
                ConsentRecord,
                (ConsentRecord.landowner_id == Landowner.id) & (ConsentRecord.sop_stage == stage),
            )
            .where(
                LandRecord.project_id == project_id,
                ConsentRecord.consent_status == "agreed",
            )
        )
        or 0
    )

    headcount_ratio = headcount_agreed / headcount_total if headcount_total > 0 else 0.0
    land_share_ratio = land_share_agreed_sqm / land_share_total_sqm if land_share_total_sqm > 0 else 0.0

    return {
        "stage": stage,
        "headcount_total": headcount_total,
        "headcount_agreed": headcount_agreed,
        "headcount_ratio": headcount_ratio,
        "land_share_total_sqm": land_share_total_sqm,
        "land_share_agreed_sqm": land_share_agreed_sqm,
        "land_share_ratio": land_share_ratio,
        "dual_gate_passed": headcount_ratio >= threshold and land_share_ratio >= threshold,
    }
