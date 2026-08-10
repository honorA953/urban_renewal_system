from datetime import date, datetime

from pydantic import BaseModel, Field


class ContactLogCreate(BaseModel):
    landowner_id: int
    contact_date: datetime
    contact_method: str = Field(default="phone", pattern="^(phone|visit|mail|email|briefing|other)$")
    contact_result: str = Field(default="undecided", pattern="^(no_answer|agreed|opposed|undecided|callback_needed)$")
    notes: str | None = None
    next_follow_up_date: date | None = None


class ContactLogRead(BaseModel):
    id: int
    project_id: int
    landowner_id: int
    contact_date: datetime
    contact_method: str
    contact_result: str
    staff_id: int | None = None
    notes: str | None = None
    next_follow_up_date: date | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class AlertItem(BaseModel):
    landowner_id: int
    landowner_name: str
    contact_status: str
    last_contact_date: datetime | None = None
    days_since_last_contact: int | None = None
