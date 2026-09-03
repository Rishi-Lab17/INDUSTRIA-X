"""Audit helper — every important action is recorded, filterable later."""
import json

from .core.security import utcnow_iso
from .db import connect


def log_event(action: str, detail: dict | None = None,
              company_id: int | None = None,
              user_id: int | None = None, ip: str | None = None,
              entity_type: str | None = None,
              entity_id: int | None = None) -> None:
    con = connect()
    try:
        con.execute(
            "INSERT INTO audit_events (company_id, user_id, action, detail,"
            " entity_type, entity_id, ip, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (company_id, user_id, action, json.dumps(detail or {}),
             entity_type, entity_id, ip, utcnow_iso()),
        )
        con.commit()
    finally:
        con.close()
