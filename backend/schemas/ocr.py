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


class OcrMatchResultRead(BaseModel):
    id: int
    ocr_job_id: int
    extracted_name: str | None = None
    extracted_id_number: str | None = None
    extracted_parcel_number: str | None = None
    extracted_section: str | None = None
    extracted_address: str | None = None
    extracted_total_area_sqm: float | None = None
    extracted_ownership_numerator: int | None = None
    extracted_ownership_denominator: int | None = None
    raw_text: str | None = None
    review_status: str

    model_config = {"from_attributes": True}


class OcrExtractionResult(BaseModel):
    """Response for a completed (or failed) OCR extraction, ready for the
    frontend to pre-fill the 新增地主 form. All fields are best-effort
    suggestions and must be reviewed by the user before saving."""

    job: OcrJobRead
    match: OcrMatchResultRead | None = None
