from datetime import datetime

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    project_code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=255)
    address: str | None = None
    city: str | None = None
    district: str | None = None
    description: str | None = None


class ProjectUpdate(BaseModel):
    name: str | None = None
    address: str | None = None
    city: str | None = None
    district: str | None = None
    status: str | None = Field(default=None, pattern="^(active|closed|suspended)$")
    description: str | None = None


class ProjectRead(BaseModel):
    id: int
    project_code: str
    name: str
    address: str | None = None
    city: str | None = None
    district: str | None = None
    status: str
    current_stage: int
    is_force_closed: bool
    description: str | None = None
    created_by: int | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BatchDeleteRequest(BaseModel):
    project_ids: list[int] = Field(min_length=1)
    admin_username: str
    admin_password: str


class BatchDeleteResult(BaseModel):
    deleted_ids: list[int]
    not_found_ids: list[int]


class ConsentRatio(BaseModel):
    stage: int
    headcount_total: int
    headcount_agreed: int
    headcount_ratio: float
    land_share_total_sqm: float
    land_share_agreed_sqm: float
    land_share_ratio: float
    dual_gate_passed: bool
