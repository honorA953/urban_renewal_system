from datetime import datetime

from pydantic import BaseModel, Field


class LandRecordCreate(BaseModel):
    parcel_number: str = Field(min_length=1, max_length=100)
    township: str | None = None
    section: str | None = None
    subsection: str | None = None
    registration_order: str | None = None
    total_area_sqm: float = 0
    ownership_numerator: int = Field(default=1, gt=0)
    ownership_denominator: int = Field(default=1, gt=0)


class LandRecordUpdate(BaseModel):
    parcel_number: str | None = Field(default=None, min_length=1, max_length=100)
    township: str | None = None
    section: str | None = None
    subsection: str | None = None
    registration_order: str | None = None
    total_area_sqm: float | None = None
    ownership_numerator: int | None = Field(default=None, gt=0)
    ownership_denominator: int | None = Field(default=None, gt=0)


class LandRecordRead(BaseModel):
    id: int
    landowner_id: int | None = None
    parcel_number: str
    township: str | None = None
    section: str | None = None
    subsection: str | None = None
    registration_order: str | None = None
    total_area_sqm: float
    ownership_numerator: int
    ownership_denominator: int
    owned_area_sqm: float | None = None
    ownership_share_pct: float | None = None

    model_config = {"from_attributes": True}


class BuildingRecordCreate(BaseModel):
    land_record_id: int | None = None
    building_number: str | None = None
    address: str | None = None
    floor: str | None = None
    total_floors: str | None = None
    registration_order: str | None = None
    structure_area_sqm: float = 0
    auxiliary_area_sqm: float = 0
    common_area_sqm: float = 0
    ownership_numerator: int = Field(default=1, gt=0)
    ownership_denominator: int = Field(default=1, gt=0)


class BuildingRecordUpdate(BaseModel):
    land_record_id: int | None = None
    building_number: str | None = None
    address: str | None = None
    floor: str | None = None
    total_floors: str | None = None
    registration_order: str | None = None
    structure_area_sqm: float | None = None
    auxiliary_area_sqm: float | None = None
    common_area_sqm: float | None = None
    ownership_numerator: int | None = Field(default=None, gt=0)
    ownership_denominator: int | None = Field(default=None, gt=0)


class BuildingRecordRead(BaseModel):
    id: int
    landowner_id: int | None = None
    land_record_id: int | None = None
    building_number: str | None = None
    address: str | None = None
    floor: str | None = None
    total_floors: str | None = None
    registration_order: str | None = None
    structure_area_sqm: float
    auxiliary_area_sqm: float
    common_area_sqm: float
    total_area_sqm: float
    ownership_numerator: int
    ownership_denominator: int
    ownership_share_pct: float

    model_config = {"from_attributes": True}


class LandownerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    id_number: str | None = None
    phone: str | None = None
    address: str | None = None
    is_representative: bool = False
    notes: str | None = None
    land_records: list[LandRecordCreate] = []
    building_records: list[BuildingRecordCreate] = []


class LandownerUpdate(BaseModel):
    name: str | None = None
    id_number: str | None = None
    phone: str | None = None
    address: str | None = None
    contact_status: str | None = Field(default=None, pattern="^(not_contacted|contacted|declined|agreed)$")
    is_representative: bool | None = None
    notes: str | None = None


class LandownerMergeRequest(BaseModel):
    source_ids: list[int] = Field(min_length=1)


class LandownerRead(BaseModel):
    id: int
    project_id: int
    name: str
    id_number: str | None = None
    phone: str | None = None
    address: str | None = None
    contact_status: str
    is_representative: bool
    notes: str | None = None
    created_at: datetime
    updated_at: datetime
    land_records: list[LandRecordRead] = []
    building_records: list[BuildingRecordRead] = []

    model_config = {"from_attributes": True}
