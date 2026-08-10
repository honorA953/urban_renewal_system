from datetime import datetime
from typing import Any

from pydantic import BaseModel


class SopStatusResponse(BaseModel):
    project_id: int
    current_stage: int
    stages: dict[str, Any]
    final: dict[str, Any]
    updated_at: datetime


class SopCompleteRequest(BaseModel):
    force: bool = False
    reason: str | None = None


class ConsentUpsertRequest(BaseModel):
    landowner_id: int
    consent_status: str
    notes: str | None = None


class ConsentRecordRead(BaseModel):
    id: int
    landowner_id: int
    sop_stage: int
    consent_status: str
    recorded_at: datetime
    recorded_by: int | None = None
    notes: str | None = None

    model_config = {"from_attributes": True}
