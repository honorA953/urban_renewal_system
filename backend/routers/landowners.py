from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from database import get_db
from deps import get_current_user, require_staff_or_admin
from models.building_record import BuildingRecord
from models.consent_record import ConsentRecord
from models.contact_log import ContactLog
from models.document import Document
from models.land_record import LandRecord
from models.landowner import Landowner
from models.user import User
from routers.projects import assert_project_visible, get_project_or_404
from routers.sop import try_auto_complete_stage
from schemas.landowner import (
    BuildingRecordCreate,
    BuildingRecordRead,
    BuildingRecordUpdate,
    LandownerCreate,
    LandownerMergeRequest,
    LandownerRead,
    LandownerUpdate,
    LandRecordCreate,
    LandRecordRead,
    LandRecordUpdate,
)

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

    # Adding the first landowner satisfies stage 1's gate (謄本OCR/地主清冊) -
    # auto-advance the SOP instead of requiring a separate manual "complete" click.
    try_auto_complete_stage(db, project_id, stage=1, current_user=current_user)

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


@router.post("/{landowner_id}/merge", response_model=LandownerRead)
def merge_landowners(
    project_id: int,
    landowner_id: int,
    payload: LandownerMergeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff_or_admin),
):
    """Merges one or more duplicate landowner records into `landowner_id` (the
    survivor): every land/building record, consent record, contact log, and document
    reference that pointed at a source landowner is re-pointed at the survivor, then the
    now-empty source rows are deleted. Needed because landowner de-duplication during OCR
    import matches by exact name string - a residual simplified-character or OCR misread
    that slips past that matching silently creates a second landowner instead of merging
    into the existing one, and this is the cleanup path for when that already happened."""
    survivor = get_landowner_or_404(db, project_id, landowner_id)

    if landowner_id in payload.source_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能將地主合併到自己")

    sources = db.scalars(
        select(Landowner).where(Landowner.id.in_(payload.source_ids), Landowner.project_id == project_id)
    ).all()
    if len(sources) != len(set(payload.source_ids)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="部分地主不存在")

    source_ids = [source.id for source in sources]
    for model in (LandRecord, BuildingRecord, ConsentRecord, ContactLog, Document):
        db.execute(update(model).where(model.landowner_id.in_(source_ids)).values(landowner_id=landowner_id))

    for source in sources:
        db.delete(source)

    db.commit()
    return get_landowner_or_404(db, project_id, survivor.id)


def get_land_record_or_404(db: Session, project_id: int, landowner_id: int, record_id: int) -> LandRecord:
    record = db.scalar(
        select(LandRecord).where(
            LandRecord.id == record_id, LandRecord.project_id == project_id, LandRecord.landowner_id == landowner_id
        )
    )
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Land record not found")
    return record


@router.post("/{landowner_id}/land-records", response_model=LandRecordRead, status_code=status.HTTP_201_CREATED)
def create_land_record(
    project_id: int,
    landowner_id: int,
    payload: LandRecordCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff_or_admin),
):
    get_landowner_or_404(db, project_id, landowner_id)
    record = LandRecord(project_id=project_id, landowner_id=landowner_id, **payload.model_dump())
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@router.patch("/{landowner_id}/land-records/{record_id}", response_model=LandRecordRead)
def update_land_record(
    project_id: int,
    landowner_id: int,
    record_id: int,
    payload: LandRecordUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff_or_admin),
):
    record = get_land_record_or_404(db, project_id, landowner_id, record_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(record, field, value)
    db.commit()
    db.refresh(record)
    return record


@router.delete("/{landowner_id}/land-records/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_land_record(
    project_id: int,
    landowner_id: int,
    record_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff_or_admin),
):
    record = get_land_record_or_404(db, project_id, landowner_id, record_id)
    db.delete(record)
    db.commit()


def get_building_record_or_404(db: Session, project_id: int, landowner_id: int, record_id: int) -> BuildingRecord:
    record = db.scalar(
        select(BuildingRecord).where(
            BuildingRecord.id == record_id,
            BuildingRecord.project_id == project_id,
            BuildingRecord.landowner_id == landowner_id,
        )
    )
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Building record not found")
    return record


@router.post(
    "/{landowner_id}/building-records", response_model=BuildingRecordRead, status_code=status.HTTP_201_CREATED
)
def create_building_record(
    project_id: int,
    landowner_id: int,
    payload: BuildingRecordCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff_or_admin),
):
    get_landowner_or_404(db, project_id, landowner_id)
    if payload.land_record_id is not None:
        get_land_record_or_404(db, project_id, landowner_id, payload.land_record_id)
    record = BuildingRecord(project_id=project_id, landowner_id=landowner_id, **payload.model_dump())
    _compute_building_totals(record)
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@router.patch("/{landowner_id}/building-records/{record_id}", response_model=BuildingRecordRead)
def update_building_record(
    project_id: int,
    landowner_id: int,
    record_id: int,
    payload: BuildingRecordUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff_or_admin),
):
    record = get_building_record_or_404(db, project_id, landowner_id, record_id)
    updates = payload.model_dump(exclude_unset=True)
    if updates.get("land_record_id") is not None:
        get_land_record_or_404(db, project_id, landowner_id, updates["land_record_id"])
    for field, value in updates.items():
        setattr(record, field, value)
    _compute_building_totals(record)
    db.commit()
    db.refresh(record)
    return record


@router.delete("/{landowner_id}/building-records/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_building_record(
    project_id: int,
    landowner_id: int,
    record_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff_or_admin),
):
    record = get_building_record_or_404(db, project_id, landowner_id, record_id)
    db.delete(record)
    db.commit()
