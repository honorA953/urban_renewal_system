from datetime import datetime

from pydantic import BaseModel


class DocumentRead(BaseModel):
    id: int
    project_id: int
    landowner_id: int | None = None
    doc_type: str
    file_name: str
    file_size_bytes: int
    mime_type: str | None = None
    uploaded_by: int | None = None
    uploaded_at: datetime
    description: str | None = None

    model_config = {"from_attributes": True}
