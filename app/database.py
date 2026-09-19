import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "salesguard.db")
DATABASE_URL = os.environ.get("DATABASE_URL") or f"sqlite:///{DB_PATH}"

_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=_connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def ensure_schema():
    """Lightweight migration: create_all() never alters existing tables, so add
    leads.source to databases created before it existed. Leads that already have
    human-audit ground truth are the seeded ones; the rest were uploaded."""
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(leads)"))] if engine.dialect.name == "sqlite" else []
        if cols and "source" not in cols:
            conn.execute(text("ALTER TABLE leads ADD COLUMN source VARCHAR NOT NULL DEFAULT 'SEEDED'"))
            conn.execute(text(
                "UPDATE leads SET source = 'UPLOADED' "
                "WHERE id NOT IN (SELECT DISTINCT lead_id FROM human_audits)"
            ))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
