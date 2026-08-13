from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_db
from deps import get_current_user, require_admin
from models.login_log import LoginLog
from models.user import User
from schemas.auth import LoginLogRead, LoginRequest, TokenResponse, UserInfo
from security import create_access_token, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _record_login_event(db: Session, user_id: int, action: str, ip_address: str | None) -> None:
    db.add(LoginLog(user_id=user_id, action=action, ip_address=ip_address))


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == payload.username))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is deactivated")

    user.last_login_at = datetime.now(timezone.utc)
    _record_login_event(db, user.id, "login", _client_ip(request))
    db.commit()

    token = create_access_token(user.id, user.role)
    return TokenResponse(access_token=token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _record_login_event(db, current_user.id, "logout", _client_ip(request))
    db.commit()


@router.get("/me", response_model=UserInfo)
def me(current_user: User = Depends(get_current_user)):
    return current_user


@router.get("/login-logs", response_model=list[LoginLogRead])
def list_login_logs(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    rows = db.execute(
        select(LoginLog, User)
        .join(User, User.id == LoginLog.user_id)
        .order_by(LoginLog.occurred_at.desc())
    ).all()
    return [
        LoginLogRead(
            id=log.id,
            user_id=log.user_id,
            username=user.username,
            display_name=user.display_name,
            role=user.role,
            action=log.action,
            occurred_at=log.occurred_at,
            ip_address=log.ip_address,
        )
        for log, user in rows
    ]
