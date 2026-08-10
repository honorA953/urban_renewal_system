from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from database import get_db
from deps import get_current_user, require_staff_or_admin
from models.building_record import BuildingRecord
from models.land_record import LandRecord
from models.landowner import Landowner
from models.user import User
from routers.projects import assert_project_visible, get_project_or_404
from schemas.landowner import LandownerCreate, LandownerRead, LandownerUpdate

router = APIRouter(prefix="/projects/{project_id}/landowners", tags=["landowners"])


def _with_records(stmt):
    return stmt.options(selectinload(Landowner.land_records), selectinload(Landowner.building_records))


def get_landowner_or_404(db: Session, project_id: int, landowner_id: int) -> Landowner:
    landowner = db.scalar(
        _with_records(
            select(Landowner).where(Landowner.id == landowner_id, Landowner.project_id == project_id)
        )
    )
    if landowner is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Landowner not found")
    return landowner


def _compute_building_totals(record: BuildingRecord) -> None:
    record.total_area_sqm = (
        float(record.structure_area_sqm) + float(record.auxiliary_area_sqm) + float(record.common_area_sqm)
    )
    record.ownership_share_pct = (
        record.ownership_numerator / record.ownership_denominator * 100 if record.ownership_denominator else 0
    )


@router.get("", response_model=list[LandownerRead])
def list_landowners(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_project_or_404(db, project_id)
    assert_project_visible(db, project, current_user)
    return db.scalars(_with_records(select(Landowner).where(Landowner.project_id == project_id))).all()


@router.post("", response_model=LandownerRead, status_code=status.HTTP_201_CREATED)
def create_landowner(
    project_id: int,
    payload: LandownerCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff_or_admin),
):
    get_project_or_404(db, project_id)

    data = payload.model_dump(exclude={"land_records", "building_records"})
    landowner = Landowner(project_id=project_id, **data)
    db.add(landowner)
    db.flush()

    for land_payload in payload.land_records:
        db.add(LandRecord(project_id=project_id, landowner_id=landowner.id, **land_payload.model_dump()))

    for building_payload in payload.building_records:
        record = BuildingRecord(project_id=project_id, landowner_id=landowner.id, **building_payload.model_dump())
        _compute_building_totals(record)
        db.add(record)

    db.commit()
    return get_landowner_or_404(db, project_id, landowner.id)


@router.get("/{landowner_id}", response_model=LandownerRead)
def get_landowner(
    project_id: int,
    landowner_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_project_or_404(db, project_id)
    assert_project_visible(db, project, current_user)
    return get_landowner_or_404(db, project_id, landowner_id)


@router.patch("/{landowner_id}", response_model=LandownerRead)
def update_landowner(
    project_id: int,
    landowner_id: int,
    payload: LandownerUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff_or_admin),
):
    landowner = get_landowner_or_404(db, project_id, landowner_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(landowner, field, value)
    db.commit()
    return get_landowner_or_404(db, project_id, landowner_id)


@router.delete("/{landowner_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_landowner(
    project_id: int,
    landowner_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff_or_admin),
):
    landowner = get_landowner_or_404(db, project_id, landowner_id)
    db.delete(landowner)
    db.commit()
