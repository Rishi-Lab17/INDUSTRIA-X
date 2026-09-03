"""Equipment management + digital passport + QR + per-asset history.

Tenant rule: every query is scoped to the session's company_id. A foreign id
returns 404 (never reveals existence). RBAC: create/update = ADMIN+ENGINEER,
deactivate = ADMIN only, read/QR = all roles, history = ADMIN+ENGINEER.
"""
import io
import json
import re
from datetime import date

import qrcode
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, field_validator

from ..audit import log_event
from ..core.deps import get_current_session, require_roles
from ..core.security import utcnow_iso
from ..db import connect

router = APIRouter(prefix="/api/equipment", tags=["equipment"])

CRITICALITY = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
STATUS = ("OPERATIONAL", "DEGRADED", "UNDER_MAINTENANCE", "DECOMMISSIONED")
_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-_/.]{0,31}$")
_STR_FIELDS = ("manufacturer", "model", "serial_number", "location")
_MAX_STR = 128


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _check_date(v: str | None, field: str) -> str | None:
    if v is None or not str(v).strip():
        return None
    try:
        return date.fromisoformat(str(v).strip()).isoformat()
    except ValueError:
        raise ValueError(f"{field} must be YYYY-MM-DD")


class EquipmentIn(BaseModel):
    code: str
    name: str
    type: str
    manufacturer: str = ""
    model: str = ""
    serial_number: str = ""
    location: str = ""
    criticality: str = "MEDIUM"
    status: str = "OPERATIONAL"
    installed_at: str | None = None
    commissioned_at: str | None = None
    metadata: dict | None = None

    @field_validator("code")
    @classmethod
    def _code(cls, v: str) -> str:
        v = v.strip()
        if not _CODE_RE.match(v):
            raise ValueError("code: 1-32 chars, letters/digits/-_/., e.g. P-204")
        return v

    @field_validator("name", "type")
    @classmethod
    def _nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Must not be empty")
        return v.strip()[:_MAX_STR]

    @field_validator("manufacturer", "model", "serial_number", "location")
    @classmethod
    def _bounded(cls, v: str) -> str:
        return v.strip()[:_MAX_STR]

    @field_validator("criticality")
    @classmethod
    def _crit(cls, v: str) -> str:
        if v not in CRITICALITY:
            raise ValueError(f"criticality must be one of {CRITICALITY}")
        return v

    @field_validator("status")
    @classmethod
    def _status(cls, v: str) -> str:
        if v not in STATUS:
            raise ValueError(f"status must be one of {STATUS}")
        return v

    @field_validator("installed_at", "commissioned_at")
    @classmethod
    def _dates(cls, v: str | None, info) -> str | None:
        return _check_date(v, info.field_name)


class EquipmentPatchIn(BaseModel):
    code: str | None = None
    name: str | None = None
    type: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    serial_number: str | None = None
    location: str | None = None
    criticality: str | None = None
    status: str | None = None
    installed_at: str | None = None
    commissioned_at: str | None = None
    metadata: dict | None = None

    @field_validator("code")
    @classmethod
    def _code(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not _CODE_RE.match(v):
            raise ValueError("code: 1-32 chars, letters/digits/-_/., e.g. P-204")
        return v

    @field_validator("name", "type", "manufacturer", "model",
                     "serial_number", "location")
    @classmethod
    def _str(cls, v: str | None, info) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if info.field_name in ("name", "type") and not v:
            raise ValueError("Must not be empty")
        return v[:_MAX_STR]

    @field_validator("criticality")
    @classmethod
    def _crit(cls, v: str | None) -> str | None:
        if v is not None and v not in CRITICALITY:
            raise ValueError(f"criticality must be one of {CRITICALITY}")
        return v

    @field_validator("status")
    @classmethod
    def _status(cls, v: str | None) -> str | None:
        if v is not None and v not in STATUS:
            raise ValueError(f"status must be one of {STATUS}")
        return v

    @field_validator("installed_at", "commissioned_at")
    @classmethod
    def _dates(cls, v: str | None, info) -> str | None:
        # None = untouched; empty string = clear the date.
        if v is None:
            return None
        return _check_date(v, info.field_name)


def _row_to_passport(row) -> dict:
    try:
        metadata = json.loads(row["metadata"])
    except (ValueError, TypeError):
        metadata = {}
    return {
        "id": row["id"], "code": row["code"], "name": row["name"],
        "type": row["type"], "manufacturer": row["manufacturer"],
        "model": row["model"], "serial_number": row["serial_number"],
        "location": row["location"], "criticality": row["criticality"],
        "status": row["status"], "installed_at": row["installed_at"],
        "commissioned_at": row["commissioned_at"], "metadata": metadata,
        "is_active": bool(row["is_active"]),
        "created_at": row["created_at"], "updated_at": row["updated_at"],
    }


def _get_owned(con, equipment_id: int, company_id: int, include_inactive=False):
    q = ("SELECT * FROM equipment WHERE id = ? AND company_id = ?"
         + ("" if include_inactive else " AND is_active = 1"))
    row = con.execute(q, (equipment_id, company_id)).fetchone()
    if row is None:
        # Deliberately 404 for foreign/missing ids: no existence oracle.
        raise HTTPException(status_code=404, detail="Equipment not found")
    return row


def qr_payload(company_id: int, equipment_id: int, code: str) -> str:
    return json.dumps({"v": 1, "app": "INDUSTRIA-X", "company_id": company_id,
                       "equipment_id": equipment_id, "code": code,
                       "passport_url": f"/equipment/{equipment_id}"},
                      separators=(",", ":"))


@router.get("")
def list_equipment(sess: dict = Depends(get_current_session),
                   status: str | None = None, criticality: str | None = None,
                   q: str | None = None):
    if status is not None and status not in STATUS:
        raise HTTPException(status_code=422, detail=f"status must be one of {STATUS}")
    if criticality is not None and criticality not in CRITICALITY:
        raise HTTPException(status_code=422,
                            detail=f"criticality must be one of {CRITICALITY}")
    query = "SELECT * FROM equipment WHERE company_id = ? AND is_active = 1"
    params: list = [sess["company_id"]]
    if status:
        query += " AND status = ?"
        params.append(status)
    if criticality:
        query += " AND criticality = ?"
        params.append(criticality)
    if q and q.strip():
        query += " AND (code LIKE ? OR name LIKE ?)"
        params += [f"%{q.strip()}%", f"%{q.strip()}%"]
    query += " ORDER BY id"
    con = connect()
    try:
        rows = con.execute(query, params).fetchall()
    finally:
        con.close()
    return {"equipment": [_row_to_passport(r) for r in rows]}


@router.post("", status_code=201,
             dependencies=[Depends(require_roles("COMPANY_ADMIN", "ENGINEER"))])
def create_equipment(body: EquipmentIn, request: Request,
                     sess: dict = Depends(get_current_session)):
    con = connect()
    try:
        if con.execute("SELECT 1 FROM equipment WHERE company_id = ? AND code = ?",
                       (sess["company_id"], body.code)).fetchone():
            raise HTTPException(status_code=409,
                                detail="Equipment code already exists in this company")
        cur = con.execute(
            "INSERT INTO equipment (company_id, code, name, type, manufacturer, model,"
            " serial_number, location, criticality, status, installed_at,"
                " commissioned_at, metadata, created_by, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (sess["company_id"], body.code, body.name, body.type,
             body.manufacturer, body.model, body.serial_number, body.location,
             body.criticality, body.status, body.installed_at, body.commissioned_at,
             json.dumps(body.metadata or {}), sess["user_id"],
             utcnow_iso(), utcnow_iso()))
        eq_id = cur.lastrowid
        con.commit()
        row = con.execute("SELECT * FROM equipment WHERE id = ?", (eq_id,)).fetchone()
    finally:
        con.close()
    log_event("equipment_created", {"code": body.code, "name": body.name},
              company_id=sess["company_id"], user_id=sess["user_id"],
              ip=_client_ip(request), entity_type="equipment", entity_id=eq_id)
    return _row_to_passport(row)


@router.get("/{equipment_id}")
def get_equipment(equipment_id: int, sess: dict = Depends(get_current_session)):
    con = connect()
    try:
        row = _get_owned(con, equipment_id, sess["company_id"])
    finally:
        con.close()
    return _row_to_passport(row)


@router.patch("/{equipment_id}",
              dependencies=[Depends(require_roles("COMPANY_ADMIN", "ENGINEER"))])
def update_equipment(equipment_id: int, body: EquipmentPatchIn, request: Request,
                     sess: dict = Depends(get_current_session)):
    updates = body.model_dump(exclude_unset=True)
    meta = updates.pop("metadata", None)
    if meta is not None:
        updates["metadata"] = json.dumps(meta)
    con = connect()
    try:
        _get_owned(con, equipment_id, sess["company_id"])
        if "code" in updates and con.execute(
                "SELECT 1 FROM equipment WHERE company_id = ? AND code = ? AND id != ?",
                (sess["company_id"], updates["code"], equipment_id)).fetchone():
            raise HTTPException(status_code=409,
                                detail="Equipment code already exists in this company")
        changed = sorted(updates)
        if updates:
            updates["updated_at"] = utcnow_iso()
            sets = ", ".join(f"{k} = ?" for k in updates)
            con.execute(f"UPDATE equipment SET {sets} WHERE id = ?",
                        (*updates.values(), equipment_id))
            con.commit()
        row = con.execute("SELECT * FROM equipment WHERE id = ?", (equipment_id,)).fetchone()
    finally:
        con.close()
    if changed:
        log_event("equipment_updated", {"changed": changed},
                  company_id=sess["company_id"], user_id=sess["user_id"],
                  ip=_client_ip(request), entity_type="equipment", entity_id=equipment_id)
    return _row_to_passport(row)


@router.delete("/{equipment_id}", dependencies=[Depends(require_roles("COMPANY_ADMIN"))])
def deactivate_equipment(equipment_id: int, request: Request,
                         sess: dict = Depends(get_current_session)):
    con = connect()
    try:
        row = _get_owned(con, equipment_id, sess["company_id"])
        con.execute("UPDATE equipment SET is_active = 0, updated_at = ? WHERE id = ?",
                    (utcnow_iso(), equipment_id))
        con.commit()
        code = row["code"]
    finally:
        con.close()
    log_event("equipment_deactivated", {"code": code},
              company_id=sess["company_id"], user_id=sess["user_id"],
              ip=_client_ip(request), entity_type="equipment", entity_id=equipment_id)
    return {"message": f"Equipment {code} deactivated."}


@router.get("/{equipment_id}/qr")
def equipment_qr(equipment_id: int, sess: dict = Depends(get_current_session)):
    con = connect()
    try:
        row = _get_owned(con, equipment_id, sess["company_id"])
    finally:
        con.close()
    payload = qr_payload(sess["company_id"], equipment_id, row["code"])
    img = qrcode.make(payload, box_size=8, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png",
                    headers={"X-QR-Payload": payload})


@router.get("/{equipment_id}/history",
            dependencies=[Depends(require_roles("COMPANY_ADMIN", "ENGINEER"))])
def equipment_history(equipment_id: int, sess: dict = Depends(get_current_session),
                      limit: int = 50):
    limit = max(1, min(limit, 200))
    con = connect()
    try:
        _get_owned(con, equipment_id, sess["company_id"], include_inactive=True)
        rows = con.execute(
            "SELECT id, user_id, action, detail, created_at FROM audit_events"
            " WHERE company_id = ? AND entity_type = 'equipment' AND entity_id = ?"
            " ORDER BY id DESC LIMIT ?", (sess["company_id"], equipment_id, limit)).fetchall()
    finally:
        con.close()
    return {"history": [dict(r) for r in rows]}
