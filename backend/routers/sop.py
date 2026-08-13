from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from database import get_db
from deps import get_current_user, require_admin, require_staff_or_admin
from models.consent_record import ConsentRecord
from models.landowner import Landowner
from models.sop import SopStage
from models.user import User
from routers.projects import assert_project_visible, get_project_or_404
from schemas.sop import (
    ConsentRecordRead,
    ConsentUpsertRequest,
    SopCompleteRequest,
    SopStatusResponse,
)
from utils.consent_ratio import calculate_consent_ratio

router = APIRouter(prefix="/projects/{project_id}/sop", tags=["sop"])

STAGE_DEFINITIONS: list[tuple[str, dict]] = [
    ("第0關:初始核定立案", {}),
    ("第1關:謄本OCR/地主清冊", {}),
    ("第2關:聯絡率>95%", {"contact_rate_threshold": 0.95}),
    ("第3關:說明會#1", {}),
    ("第4關:同意度>80%(雙門檻)", {"headcount_threshold": 0.8, "land_share_threshold": 0.8}),
    ("第5關:顧問文件主管審核", {}),
    ("第6關:說明會#2(圖面發布)", {}),
    ("第7關:說明會#3(合約Q&A)", {}),
    ("第8關:說明會#4同意度>80%", {"headcount_threshold": 0.8, "land_share_threshold": 0.8}),
    ("第9關:雙門檻同意>80%", {"headcount_threshold": 0.8, "land_share_threshold": 0.8}),
]

DUAL_GATE_STAGES = {4, 8, 9}
CONTACT_RATE_STAGE = 2
CONTACT_RATE_THRESHOLD = 0.95
FINAL_STAGE = 9


def build_initial_stage_data() -> dict:
    return {
        "stages": {
            str(i): {
                "name": name,
                "status": "completed" if i == 0 else "pending",
                "data": dict(extra),
            }
            for i, (name, extra) in enumerate(STAGE_DEFINITIONS)
        },
        "final": {"status": "pending", "force_closed": False, "closed_at": None, "closed_by": None},
    }


def get_or_create_sop(db: Session, project_id: int) -> SopStage:
    sop = db.scalar(select(SopStage).where(SopStage.project_id == project_id))
    if sop is None:
        sop = SopStage(project_id=project_id, stage_data=build_initial_stage_data(), current_stage=1)
        db.add(sop)
        db.commit()
        db.refresh(sop)
    return sop


def _status_response(project_id: int, sop: SopStage) -> SopStatusResponse:
    return SopStatusResponse(
        project_id=project_id,
        current_stage=sop.current_stage,
        stages=sop.stage_data["stages"],
        final=sop.stage_data["final"],
        updated_at=sop.updated_at,
    )


def _assert_gate_passed(db: Session, project_id: int, stage: int) -> None:
    if stage == 1:
        total = db.scalar(select(func.count(Landowner.id)).where(Landowner.project_id == project_id)) or 0
        if total < 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Stage 1 requires at least one landowner record",
            )
    elif stage == CONTACT_RATE_STAGE:
        total = db.scalar(select(func.count(Landowner.id)).where(Landowner.project_id == project_id)) or 0
        reached = db.scalar(
            select(func.count(Landowner.id)).where(
                Landowner.project_id == project_id, Landowner.contact_status != "not_contacted"
            )
        ) or 0
        ratio = reached / total if total > 0 else 0.0
        if ratio < CONTACT_RATE_THRESHOLD:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Contact rate {ratio:.1%} is below the {CONTACT_RATE_THRESHOLD:.0%} threshold",
            )
    elif stage in DUAL_GATE_STAGES:
        ratio = calculate_consent_ratio(db, project_id, stage)
        if not ratio["dual_gate_passed"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Dual-gate not met: headcount {ratio['headcount_ratio']:.1%}, "
                    f"land share {ratio['land_share_ratio']:.1%} (need >= 80% both)"
                ),
            )
    # stages 0, 3, 5, 6, 7 have no automated gate - manual milestone confirmation only.


def try_auto_complete_stage(db: Session, project_id: int, stage: int, current_user: User) -> None:
    """Best-effort: marks `stage` completed (without committing - the caller's own
    commit covers it) if it's still the project's current pending stage and its gate
    condition is already satisfied. Used to auto-advance the SOP when underlying data
    crosses a gate threshold outside of an explicit "complete stage" action - e.g.
    creating the first landowner clears stage 1's gate. Silently no-ops otherwise."""
    sop = get_or_create_sop(db, project_id)
    if sop.current_stage != stage:
        return
    stage_key = str(stage)
    stage_entry = sop.stage_data["stages"].get(stage_key)
    if not stage_entry or stage_entry["status"] != "pending":
        return
    try:
        _assert_gate_passed(db, project_id, stage)
    except HTTPException:
        return

    stage_data = dict(sop.stage_data)
    stages = dict(stage_data["stages"])
    entry = dict(stages[stage_key])
    entry["status"] = "completed"
    entry["completed_at"] = datetime.now(timezone.utc).isoformat()
    entry["completed_by"] = current_user.id
    stages[stage_key] = entry
    stage_data["stages"] = stages
    sop.stage_data = stage_data
    sop.current_stage = min(stage + 1, FINAL_STAGE)

    project = get_project_or_404(db, project_id)
    project.current_stage = sop.current_stage


@router.get("", response_model=SopStatusResponse)
def get_sop_status(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_project_or_404(db, project_id)
    assert_project_visible(db, project, current_user)
    sop = get_or_create_sop(db, project_id)
    return _status_response(project_id, sop)


@router.post("/{stage}/complete", response_model=SopStatusResponse)
def complete_stage(
    project_id: int,
    stage: int,
    payload: SopCompleteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff_or_admin),
):
    project = get_project_or_404(db, project_id)
    sop = get_or_create_sop(db, project_id)

    if not (0 <= stage <= FINAL_STAGE):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid stage number")

    if payload.force and current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only admin can force-complete a stage")

    if stage != sop.current_stage and not payload.force:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Stage {stage} is not the current stage ({sop.current_stage})",
        )

    stage_data = dict(sop.stage_data)
    stages = dict(stage_data["stages"])
    stage_key = str(stage)
    stage_entry = dict(stages[stage_key])

    if payload.force:
        stage_entry["status"] = "force_closed"
        stage_entry["forced_reason"] = payload.reason
    else:
        _assert_gate_passed(db, project_id, stage)
        stage_entry["status"] = "completed"

    stage_entry["completed_at"] = datetime.now(timezone.utc).isoformat()
    stage_entry["completed_by"] = current_user.id
    stages[stage_key] = stage_entry
    stage_data["stages"] = stages

    if stage == sop.current_stage:
        sop.current_stage = min(stage + 1, FINAL_STAGE)

    sop.stage_data = stage_data
    project.current_stage = sop.current_stage

    if stage == FINAL_STAGE and stage_entry["status"] in ("completed", "force_closed"):
        _maybe_auto_close(db, project, sop, stage_data)

    db.commit()
    db.refresh(sop)
    return _status_response(project_id, sop)


def _maybe_auto_close(db: Session, project, sop: SopStage, stage_data: dict) -> None:
    ratio = calculate_consent_ratio(db, project.id, FINAL_STAGE)
    if ratio["headcount_total"] > 0 and ratio["headcount_ratio"] >= 1.0:
        stage_data["final"] = {
            "status": "completed",
            "force_closed": False,
            "closed_at": datetime.now(timezone.utc).isoformat(),
            "closed_by": None,
        }
        sop.stage_data = stage_data
        project.status = "closed"


@router.post("/force-close", response_model=SopStatusResponse)
def force_close_project(
    project_id: int,
    payload: SopCompleteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    project = get_project_or_404(db, project_id)
    sop = get_or_create_sop(db, project_id)

    stage_data = dict(sop.stage_data)
    stage_data["final"] = {
        "status": "force_closed",
        "force_closed": True,
        "closed_at": datetime.now(timezone.utc).isoformat(),
        "closed_by": current_user.id,
        "reason": payload.reason,
    }
    sop.stage_data = stage_data
    project.status = "closed"
    project.is_force_closed = True

    db.commit()
    db.refresh(sop)
    return _status_response(project_id, sop)


@router.get("/{stage}/consent", response_model=list[ConsentRecordRead])
def list_consent_records(
    project_id: int,
    stage: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_project_or_404(db, project_id)
    assert_project_visible(db, project, current_user)
    return db.scalars(
        select(ConsentRecord).where(ConsentRecord.project_id == project_id, ConsentRecord.sop_stage == stage)
    ).all()


@router.post("/{stage}/consent", response_model=ConsentRecordRead, status_code=status.HTTP_201_CREATED)
def upsert_consent_record(
    project_id: int,
    stage: int,
    payload: ConsentUpsertRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff_or_admin),
):
    get_project_or_404(db, project_id)

    landowner = db.get(Landowner, payload.landowner_id)
    if landowner is None or landowner.project_id != project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Landowner not found in this project")

    record = db.scalar(
        select(ConsentRecord).where(
            ConsentRecord.landowner_id == payload.landowner_id, ConsentRecord.sop_stage == stage
        )
    )
    if record is None:
        record = ConsentRecord(project_id=project_id, landowner_id=payload.landowner_id, sop_stage=stage)
        db.add(record)

    record.consent_status = payload.consent_status
    record.notes = payload.notes
    record.recorded_by = current_user.id

    db.commit()
    db.refresh(record)
    return record
