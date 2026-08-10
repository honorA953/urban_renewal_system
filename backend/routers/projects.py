from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_db
from deps import get_current_user, require_staff_or_admin
from models.project import Project, ProjectMember
from models.sop import SopStage
from models.user import User
from schemas.project import ConsentRatio, ProjectCreate, ProjectRead, ProjectUpdate
from utils.consent_ratio import calculate_consent_ratio

router = APIRouter(prefix="/projects", tags=["projects"])


def get_project_or_404(db: Session, project_id: int) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


def assert_project_visible(db: Session, project: Project, user: User) -> None:
    if user.role in ("admin", "staff"):
        return
    is_member = db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project.id, ProjectMember.user_id == user.id
        )
    )
    if is_member is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of this project")


@router.get("", response_model=list[ProjectRead])
def list_projects(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role == "public":
        stmt = (
            select(Project)
            .join(ProjectMember, ProjectMember.project_id == Project.id)
            .where(ProjectMember.user_id == current_user.id)
            .order_by(Project.created_at.desc())
        )
    else:
        stmt = select(Project).order_by(Project.created_at.desc())
    return db.scalars(stmt).all()


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff_or_admin),
):
    existing = db.scalar(select(Project).where(Project.project_code == payload.project_code))
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="project_code already exists")

    project = Project(**payload.model_dump(), created_by=current_user.id, current_stage=1)
    db.add(project)
    db.flush()

    # Stage 0 (initial filing) is pre-completed by the time a project record exists,
    # so the actionable "current" stage starts at 1.
    db.add(SopStage(project_id=project.id, stage_data=_initial_stage_data(), current_stage=1))
    db.commit()
    db.refresh(project)
    return project


@router.get("/{project_id}", response_model=ProjectRead)
def get_project(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    project = get_project_or_404(db, project_id)
    assert_project_visible(db, project, current_user)
    return project


@router.patch("/{project_id}", response_model=ProjectRead)
def update_project(
    project_id: int,
    payload: ProjectUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff_or_admin),
):
    project = get_project_or_404(db, project_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(project, field, value)
    db.commit()
    db.refresh(project)
    return project


@router.get("/{project_id}/consent-ratio", response_model=ConsentRatio)
def get_consent_ratio(
    project_id: int,
    stage: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_project_or_404(db, project_id)
    assert_project_visible(db, project, current_user)

    if stage is None:
        stage = next((s for s in (4, 8, 9) if s >= project.current_stage), 9)

    return calculate_consent_ratio(db, project_id, stage)


def _initial_stage_data() -> dict:
    from routers.sop import build_initial_stage_data

    return build_initial_stage_data()
