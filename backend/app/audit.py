"""Audit helper — every important action is recorded, filterable later."""
import json

from .core.security import utcnow_iso
from .db import connect


def log_event(action: str, detail: dict | None = None,
              company_id: int | None = None,
              user_id: int | None = None, ip: str | None = None,
              entity_type: str | None = None,
              entity_id: int | None = None) -> None:
    """Audit must never break the calling operation: writers pass real
    sessions, but adversarial/fake tenant ids fall back to NULL company
    rather than raising FK errors."""
    import sqlite3
    con = connect()
    try:
        try:
            con.execute(
                "INSERT INTO audit_events (company_id, user_id, action, detail,"
                " entity_type, entity_id, ip, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (company_id, user_id, action, json.dumps(detail or {}),
                 entity_type, entity_id, ip, utcnow_iso()),
            )
        except sqlite3.IntegrityError:
            con.execute(
                "INSERT INTO audit_events (company_id, user_id, action, detail,"
                " entity_type, entity_id, ip, created_at)"
                " VALUES (NULL, ?, ?, ?, ?, ?, ?, ?)",
                (user_id, action, json.dumps(
                    {**(detail or {}), "company_unresolved": company_id}),
                 entity_type, entity_id, ip, utcnow_iso()),
            )
        con.commit()
    finally:
        con.close()
