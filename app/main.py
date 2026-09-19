import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from .database import ensure_schema, SessionLocal
from . import models
from .routers import leads, scoring, dashboard, evaluation, admin
from .seed import seed_if_empty

app = FastAPI(title="SalesGuard QA", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.environ.get(
        "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    ensure_schema()
    db: Session = SessionLocal()
    try:
        seed_if_empty(db)
    finally:
        db.close()


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok", "service": "SalesGuard QA"}


app.include_router(leads.router)
app.include_router(scoring.router)
app.include_router(dashboard.router)
app.include_router(evaluation.router)
app.include_router(admin.router)
