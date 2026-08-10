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
