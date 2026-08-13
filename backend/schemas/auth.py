from datetime import datetime

from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserInfo(BaseModel):
    id: int
    username: str
    display_name: str
    role: str
    email: str | None = None
    phone: str | None = None

    model_config = {"from_attributes": True}


class LoginLogRead(BaseModel):
    id: int
    user_id: int
    username: str
    display_name: str
    role: str
    action: str
    occurred_at: datetime
    ip_address: str | None = None

    model_config = {"from_attributes": True}
