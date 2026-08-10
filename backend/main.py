from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from database import SessionLocal, wait_for_db
import models  # noqa: F401 - ensures all models are registered with SQLAlchemy
from routers import auth, contacts, documents, expenses, landowners, ocr, projects, sop, users
from seed import ensure_admin_account


@asynccontextmanager
async def lifespan(app: FastAPI):
    wait_for_db()
    db = SessionLocal()
    try:
        ensure_admin_account(db)
    finally:
        db.close()
    yield


app = FastAPI(title="Urban Renewal Management System API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(projects.router)
app.include_router(landowners.router)
app.include_router(contacts.router)
app.include_router(sop.router)
app.include_router(documents.router)
app.include_router(expenses.router)
app.include_router(expenses.category_router)
app.include_router(users.router)
app.include_router(ocr.router)


@app.get("/health")
def health():
    return {"ok": True}
