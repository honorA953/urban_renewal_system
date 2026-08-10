from datetime import date, datetime

from pydantic import BaseModel


class ExpenseCategoryCreate(BaseModel):
    name: str
    is_active: bool = True


class ExpenseCategoryUpdate(BaseModel):
    name: str | None = None
    is_active: bool | None = None


class ExpenseCategoryRead(BaseModel):
    id: int
    name: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class ExpenseCreate(BaseModel):
    category_id: int | None = None
    amount: float
    expense_date: date
    description: str | None = None
    vendor: str | None = None
    receipt_document_id: int | None = None


class ExpenseUpdate(BaseModel):
    category_id: int | None = None
    amount: float | None = None
    expense_date: date | None = None
    description: str | None = None
    vendor: str | None = None
    receipt_document_id: int | None = None


class ExpenseRead(BaseModel):
    id: int
    project_id: int
    category_id: int | None = None
    amount: float
    expense_date: date
    description: str | None = None
    vendor: str | None = None
    receipt_document_id: int | None = None
    created_by: int | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ExpenseSummaryItem(BaseModel):
    category_id: int | None = None
    category_name: str | None = None
    total_amount: float


class ExpenseSummary(BaseModel):
    total_amount: float
    by_category: list[ExpenseSummaryItem]
