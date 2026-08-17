from datetime import datetime

from pydantic import BaseModel


class OcrJobRead(BaseModel):
    id: int
    project_id: int
    status: str
    job_type: str
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}


class LandOwnershipEntry(BaseModel):
    registration_order: str | None = None
    owner_name: str | None = None
    id_number: str | None = None
    ownership_numerator: int | None = None
    ownership_denominator: int | None = None
    address: str | None = None


class LandParcelExtraction(BaseModel):
    township: str | None = None
    section: str | None = None
    subsection: str | None = None
    parcel_number: str | None = None
    area_sqm: float | None = None
    owners: list[LandOwnershipEntry] = []


class EncumbranceEntry(BaseModel):
    registration_order: str | None = None
    applies_to_parcels: str | None = None
    right_type: str | None = None
    right_holder: str | None = None
    debtor_info: str | None = None


class BuildingOwnershipEntry(BaseModel):
    registration_order: str | None = None
    owner_name: str | None = None
    ownership_numerator: int | None = None
    ownership_denominator: int | None = None
    address: str | None = None


class BuildingExtraction(BaseModel):
    building_number: str | None = None
    building_address: str | None = None
    parcel_number: str | None = None
    total_floors: str | None = None
    floor: str | None = None
    total_area_sqm: float | None = None
    floor_area_sqm: float | None = None
    owners: list[BuildingOwnershipEntry] = []


class TitleDeedExtraction(BaseModel):
    """The structured extraction: one entry per distinct 地號/建號 found anywhere in
    the uploaded pages (a single title deed as well as a batch covering many parcels/
    buildings both fit this shape). All fields are best-effort suggestions for the
    frontend's step-by-step review wizard, not authoritative values."""

    land_parcels: list[LandParcelExtraction] = []
    encumbrances: list[EncumbranceEntry] = []
    buildings: list[BuildingExtraction] = []


class OcrExtractionResult(BaseModel):
    job: OcrJobRead
    data: TitleDeedExtraction | None = None


class PagePreview(BaseModel):
    """One page from an uploaded file/PDF, pre-split for the wizard's manual grouping
    step - lets the user see every page and decide which ones belong together before
    any of them are sent for extraction."""

    page_number: int
    image_base64: str
    mime_type: str = "image/png"
    suggested_group: int = 1


class CasePagePreview(BaseModel):
    """One page from a batch-import upload, pre-split and labeled with which 都更案件
    it's guessed to belong to (by 鄉鎮市區+段+小段 read from the page's title) - lets the
    user review/adjust case grouping before any project is created."""

    page_number: int
    image_base64: str
    mime_type: str = "image/png"
    suggested_case_group: int = 1
    case_label: str = ""
    sample_number: str = ""


class PageSplitResult(BaseModel):
    pages: list[PagePreview]
    warning: str | None = None


class CaseDetectResult(BaseModel):
    pages: list[CasePagePreview]
    warning: str | None = None
