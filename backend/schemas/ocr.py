from datetime import datetime

from pydantic import BaseModel


class OcrJobRead(BaseModel):
    id: int
    project_id: int
    document_id: int
    status: str
    job_type: str
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}
