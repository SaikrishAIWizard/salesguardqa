"""
Read-only database browser for the hidden /database page in the UI.

- Only tables registered in the ORM metadata can be read (names are looked up
  in that dict, never interpolated into SQL).
- Strictly read-only: there are no write endpoints here.
- Card-number-like sequences are masked, exactly as in the normal API, so this
  page cannot be used to read the raw text the rest of the app redacts.
- Set ENABLE_DB_VIEWER=false in .env to switch it off (404).
"""
import datetime
import enum
import os
from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import Base, get_db
from ..services.redaction_service import redact_card_numbers

router = APIRouter(prefix="/admin/db", tags=["admin"])


def _require_enabled():
    if os.environ.get("ENABLE_DB_VIEWER", "true").strip().lower() in ("0", "false", "no", "off"):
        raise HTTPException(status_code=404, detail="Not found")


def _jsonable(value: Any) -> Any:
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    if isinstance(value, str):
        return redact_card_numbers(value)
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    return value


@router.get("/tables", dependencies=[Depends(_require_enabled)])
def list_tables(db: Session = Depends(get_db)):
    out = []
    for name, table in sorted(Base.metadata.tables.items()):
        count = db.execute(select(func.count()).select_from(table)).scalar_one()
        out.append({"name": name, "row_count": count, "column_count": len(table.columns)})
    return out


@router.get("/tables/{table_name}", dependencies=[Depends(_require_enabled)])
def read_table(
    table_name: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    table = Base.metadata.tables.get(table_name)
    if table is None:
        raise HTTPException(status_code=404, detail=f"Unknown table '{table_name}'")

    total = db.execute(select(func.count()).select_from(table)).scalar_one()
    stmt = select(table).limit(limit).offset(offset)
    pk = list(table.primary_key.columns)
    if pk:
        stmt = stmt.order_by(*pk)

    columns: List[dict] = [
        {"name": c.name, "type": str(c.type), "primary_key": c.primary_key}
        for c in table.columns
    ]
    rows = [
        {col.name: _jsonable(val) for col, val in zip(table.columns, row)}
        for row in db.execute(stmt).all()
    ]
    return {"table": table_name, "total": total, "limit": limit, "offset": offset, "columns": columns, "rows": rows}
