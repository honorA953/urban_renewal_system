from sqlalchemy import select
from sqlalchemy.orm import Session

from config import settings
from models.user import User
from security import hash_password


def ensure_admin_account(db: Session) -> None:
    existing_admin = db.scalar(select(User).where(User.role == "admin"))
    if existing_admin is not None:
        return

    admin = User(
        username="admin",
        password_hash=hash_password(settings.ADMIN_INITIAL_PASSWORD),
        display_name="系統管理員",
        role="admin",
        is_active=True,
    )
    db.add(admin)
    db.commit()
