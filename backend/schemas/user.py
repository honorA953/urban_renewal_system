from datetime import datetime

from pydantic import BaseModel, Field


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=6, max_length=72)
    display_name: str = Field(min_length=1, max_length=100)
    role: str = Field(pattern="^(admin|staff|public)$")
    email: str | None = None
    phone: str | None = None


class UserUpdate(BaseModel):
    display_name: str | None = None
    role: str | None = Field(default=None, pattern="^(admin|staff|public)$")
    email: str | None = None
    phone: str | None = None
    password: str | None = Field(default=None, min_length=6, max_length=72)


class UserActiveUpdate(BaseModel):
    is_active: bool


class UserRead(BaseModel):
    id: int
    username: str
    display_name: str
    role: str
    email: str | None = None
    phone: str | None = None
    is_active: bool
    last_login_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
