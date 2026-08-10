from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from database import get_db
from deps import get_current_user, require_admin, require_staff_or_admin
from models.expense import Expense, ExpenseCategory
from models.user import User
from routers.projects import assert_project_visible, get_project_or_404
from schemas.expense import (
    ExpenseCategoryCreate,
    ExpenseCategoryRead,
    ExpenseCategoryUpdate,
    ExpenseCreate,
    ExpenseRead,
    ExpenseSummary,
    ExpenseSummaryItem,
    ExpenseUpdate,
)

router = APIRouter(prefix="/projects/{project_id}/expenses", tags=["expenses"])
category_router = APIRouter(prefix="/expense-categories", tags=["expense-categories"])


def get_expense_or_404(db: Session, project_id: int, expense_id: int) -> Expense:
    expense = db.scalar(select(Expense).where(Expense.id == expense_id, Expense.project_id == project_id))
    if expense is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Expense not found")
    return expense


@router.get("", response_model=list[ExpenseRead])
def list_expenses(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_project_or_404(db, project_id)
    assert_project_visible(db, project, current_user)
    return db.scalars(
        select(Expense).where(Expense.project_id == project_id).order_by(Expense.expense_date.desc())
    ).all()


@router.post("", response_model=ExpenseRead, status_code=status.HTTP_201_CREATED)
def create_expense(
    project_id: int,
    payload: ExpenseCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff_or_admin),
):
    get_project_or_404(db, project_id)
    expense = Expense(project_id=project_id, created_by=current_user.id, **payload.model_dump())
    db.add(expense)
    db.commit()
    db.refresh(expense)
    return expense


@router.get("/summary", response_model=ExpenseSummary)
def expense_summary(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_project_or_404(db, project_id)
    assert_project_visible(db, project, current_user)

    total = float(
        db.scalar(select(func.coalesce(func.sum(Expense.amount), 0)).where(Expense.project_id == project_id)) or 0
    )

    rows = db.execute(
        select(
            ExpenseCategory.id, ExpenseCategory.name, func.coalesce(func.sum(Expense.amount), 0)
        )
        .select_from(Expense)
        .join(ExpenseCategory, Expense.category_id == ExpenseCategory.id, isouter=True)
        .where(Expense.project_id == project_id)
        .group_by(ExpenseCategory.id, ExpenseCategory.name)
    ).all()

    by_category = [
        ExpenseSummaryItem(category_id=row[0], category_name=row[1], total_amount=float(row[2]))
        for row in rows
    ]

    return ExpenseSummary(total_amount=total, by_category=by_category)


@router.patch("/{expense_id}", response_model=ExpenseRead)
def update_expense(
    project_id: int,
    expense_id: int,
    payload: ExpenseUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff_or_admin),
):
    expense = get_expense_or_404(db, project_id, expense_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(expense, field, value)
    db.commit()
    db.refresh(expense)
    return expense


@router.delete("/{expense_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_expense(
    project_id: int,
    expense_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff_or_admin),
):
    expense = get_expense_or_404(db, project_id, expense_id)
    db.delete(expense)
    db.commit()


@category_router.get("", response_model=list[ExpenseCategoryRead])
def list_categories(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.scalars(select(ExpenseCategory).order_by(ExpenseCategory.name)).all()


@category_router.post("", response_model=ExpenseCategoryRead, status_code=status.HTTP_201_CREATED)
def create_category(
    payload: ExpenseCategoryCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    existing = db.scalar(select(ExpenseCategory).where(ExpenseCategory.name == payload.name))
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Category name already exists")
    category = ExpenseCategory(**payload.model_dump())
    db.add(category)
    db.commit()
    db.refresh(category)
    return category


@category_router.patch("/{category_id}", response_model=ExpenseCategoryRead)
def update_category(
    category_id: int,
    payload: ExpenseCategoryUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    category = db.get(ExpenseCategory, category_id)
    if category is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(category, field, value)
    db.commit()
    db.refresh(category)
    return category


@category_router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(
    category_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    category = db.get(ExpenseCategory, category_id)
    if category is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")
    db.delete(category)
    db.commit()
