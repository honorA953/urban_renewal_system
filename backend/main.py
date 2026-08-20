from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from database import SessionLocal, wait_for_db
import models  # noqa: F401 - ensures all models are registered with SQLAlchemy
from routers import auth, contacts, documents, encumbrances, expenses, landowners, ocr, ocr_intake, projects, sop, users
from seed import ensure_admin_account


@asynccontextmanager
async def lifespan(app: FastAPI):
    wait_for_db()
    db = SessionLocal()
    try:
        ensure_admin_account(db)
    finally:
        db.close()
    # Deliberately NOT eagerly loading the RapidOCR engines here anymore - tried that to
    # shave the model-load cost off the first OCR request, but on the NAS this runs on
    # (only ~5.6GB RAM total, already shared with MariaDB/nginx/cloudflared/DSM, and
    # observed sitting at ~4.5GB used + heavy swap even before this app does anything)
    # loading both engines' models at startup instead of lazily on first use was enough
    # extra memory pressure to trigger repeated unexplained container restarts. Lazily
    # loading on first OCR call (see _get_ocr_engine/_get_header_ocr_engine in utils/ocr.py)
    # is slower for that one request but doesn't add a permanent extra footprint.
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
app.include_router(ocr_intake.router)
app.include_router(encumbrances.router)


@app.get("/health")
def health():
    return {"ok": True}
