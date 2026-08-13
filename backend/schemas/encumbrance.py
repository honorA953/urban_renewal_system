from datetime import datetime

from pydantic import BaseModel


class EncumbranceCreate(BaseModel):
    applies_to_parcels: str | None = None
    registration_order: str | None = None
    right_type: str | None = None
    right_holder: str | None = None
    debtor_info: str | None = None


class EncumbranceUpdate(BaseModel):
    applies_to_parcels: str | None = None
    registration_order: str | None = None
    right_type: str | None = None
    right_holder: str | None = None
    debtor_info: str | None = None


class EncumbranceRead(BaseModel):
    id: int
    project_id: int
    applies_to_parcels: str | None = None
    registration_order: str | None = None
    right_type: str | None = None
    right_holder: str | None = None
    debtor_info: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
