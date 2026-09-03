"""Company workspace: profile, settings (admin-only writes), member roster."""
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator

from ..audit import log_event
from ..core.deps import get_current_session, require_roles
from ..db import connect

router = APIRouter(prefix="/api/company", tags=["company"])


class CompanyPatchIn(BaseModel):
    name: str | None = None
    settings: dict | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            raise ValueError("Must not be empty")
        return v


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get("")
def get_company(sess: dict = Depends(get_current_session)):
    con = connect()
    try:
        company = con.execute("SELECT id, name, settings, created_at FROM companies"
                              " WHERE id = ?", (sess["company_id"],)).fetchone()
        if company is None:
            raise HTTPException(status_code=404, detail="Company not found")
        members = con.execute(
            "SELECT id, name, email, role, is_active, created_at FROM users"
            " WHERE company_id = ? ORDER BY id", (sess["company_id"],)).fetchall()
        n_equipment = con.execute(
            "SELECT COUNT(*) FROM equipment WHERE company_id = ? AND is_active = 1",
            (sess["company_id"],)).fetchone()[0]
    finally:
        con.close()
    try:
        settings = json.loads(company["settings"])
    except (ValueError, TypeError):
        settings = {}
    return {"company": {"id": company["id"], "name": company["name"],
                        "settings": settings, "created_at": company["created_at"]},
            "members": [dict(m) for m in members],
            "stats": {"members": len(members), "equipment": n_equipment}}


@router.patch("", dependencies=[Depends(require_roles("COMPANY_ADMIN"))])
def update_company(body: CompanyPatchIn, request: Request,
                   sess: dict = Depends(get_current_session)):
    con = connect()
    try:
        company = con.execute("SELECT id, name FROM companies WHERE id = ?",
                              (sess["company_id"],)).fetchone()
        if company is None:
            raise HTTPException(status_code=404, detail="Company not found")
        changed: dict = {}
        if body.name is not None and body.name != company["name"]:
            if con.execute("SELECT 1 FROM companies WHERE name = ? AND id != ?",
                           (body.name, sess["company_id"])).fetchone():
                raise HTTPException(status_code=409, detail="Company name already taken")
            con.execute("UPDATE companies SET name = ? WHERE id = ?",
                        (body.name, sess["company_id"]))
            changed["name"] = body.name
        if body.settings is not None:
            con.execute("UPDATE companies SET settings = ? WHERE id = ?",
                        (json.dumps(body.settings), sess["company_id"]))
            changed["settings"] = body.settings
        con.commit()
        row = con.execute("SELECT id, name, settings, created_at FROM companies WHERE id = ?",
                          (sess["company_id"],)).fetchone()
    finally:
        con.close()
    log_event("company_updated", {"changed": sorted(changed)},
              company_id=sess["company_id"], user_id=sess["user_id"],
              ip=_client_ip(request))
    return {"company": {"id": row["id"], "name": row["name"],
                        "settings": json.loads(row["settings"]),
                        "created_at": row["created_at"]}}
