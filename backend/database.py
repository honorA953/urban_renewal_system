import time

from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True, pool_recycle=280)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def wait_for_db(max_attempts: int = 15, delay_seconds: float = 2.0) -> None:
    """Retries the DB connection at startup - needed because there's no guaranteed
    startup ordering when DB_HOST points at an external MariaDB instance (e.g. on the
    NAS) instead of a docker-compose-managed service with a healthcheck."""
    last_error: Exception | None = None
    for _ in range(max_attempts):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return
        except OperationalError as exc:
            last_error = exc
            time.sleep(delay_seconds)
    raise RuntimeError(f"Could not connect to database after {max_attempts} attempts") from last_error
