"""
اتصال دیتابیس PostgreSQL
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config import settings

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    echo=settings.debug,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """Dependency برای FastAPI: یه session دیتابیس باز می‌کنه و آخرش می‌بنده"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()