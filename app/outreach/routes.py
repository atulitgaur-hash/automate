"""Outreach UI + API routes — Excel tracker, no SQLite."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from ..config import ROOT, reload_settings
from .generate import generate_email, load_profile
from .send import send_gmail
from .store import (
    STATUSES,
    email_taken,
    get_contact,
    list_companies,
    list_contacts,
    sync_from_source,
    upsert_contact,
)

router = APIRouter(tags=["outreach"])
templates = Jinja2Templates(directory=str(ROOT / "templates"))


class DraftUpdate(BaseModel):
    subject: str = ""
    body: str = ""
    notes: str = ""
    email: str = ""
    subjects: list[str] = Field(default_factory=list)


class GenerateRequest(BaseModel):
    notes: str = ""
    role: str = ""
    goal: str = ""


class BulkGenerateRequest(BaseModel):
    company: str
    limit: int = Field(default=5, ge=1, le=25)
    notes: str = ""
    only_pending: bool = True


@router.get("/outreach", response_class=HTMLResponse)
def outreach_page(request: Request):
    companies = list_companies()
    if not companies:
        try:
            sync_from_source()
            companies = list_companies()
        except Exception:
            pass
    return templates.TemplateResponse(
        request,
        "outreach.html",
        {
            "request": request,
            "companies": companies,
            "total_contacts": sum(c["total"] for c in companies),
            "profile_preview": load_profile()[:500],
            "statuses": list(STATUSES),
        },
    )


@router.post("/api/outreach/sync")
def api_sync():
    reload_settings()
    try:
        return sync_from_source()
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/api/outreach/companies")
def api_companies():
    return list_companies()


@router.get("/api/outreach/contacts")
def api_contacts(
    company: Optional[str] = None,
    status: Optional[str] = None,
    q: str = "",
    limit: int = Query(200, le=500),
):
    return [c.to_dict() for c in list_contacts(company=company, status=status, q=q, limit=limit)]


@router.get("/api/outreach/contacts/{email}")
def api_contact(email: str):
    row = get_contact(email)
    if not row:
        raise HTTPException(404, "Contact not found")
    return row.to_dict()


@router.post("/api/outreach/contacts/{email}/generate")
async def api_generate(email: str, payload: GenerateRequest):
    reload_settings()
    row = get_contact(email)
    if not row:
        raise HTTPException(404, "Contact not found")
    try:
        draft = await generate_email(
            recipient_name=row.name,
            recipient_email=row.email,
            company=row.company,
            domain=row.domain,
            role=payload.role,
            extra_notes=payload.notes or row.notes,
            goal=payload.goal or "",
        )
    except Exception as exc:  # noqa: BLE001
        row.error = str(exc)
        upsert_contact(row)
        raise HTTPException(500, str(exc)) from exc

    row.subject = draft["subject"]
    row.subjects = "\n".join(draft["subjects"])
    row.body = draft["body"]
    row.status = "drafted"
    row.error = ""
    if payload.notes:
        row.notes = payload.notes
    upsert_contact(row)
    return row.to_dict()


@router.post("/api/outreach/generate-company")
async def api_generate_company(payload: BulkGenerateRequest):
    reload_settings()
    status = "pending" if payload.only_pending else None
    rows = list_contacts(company=payload.company, status=status, limit=payload.limit)
    if not rows and payload.only_pending:
        rows = list_contacts(company=payload.company, status="rejected", limit=payload.limit)
    results = []
    errors = []
    for row in rows:
        try:
            draft = await generate_email(
                recipient_name=row.name,
                recipient_email=row.email,
                company=row.company,
                domain=row.domain,
                extra_notes=payload.notes or row.notes,
            )
            row.subject = draft["subject"]
            row.subjects = "\n".join(draft["subjects"])
            row.body = draft["body"]
            row.status = "drafted"
            row.error = ""
            if payload.notes:
                row.notes = payload.notes
            upsert_contact(row)
            results.append(row.email)
        except Exception as exc:  # noqa: BLE001
            row.error = str(exc)
            upsert_contact(row)
            errors.append({"email": row.email, "error": str(exc)})
    return {"generated": len(results), "emails": results, "errors": errors}


@router.put("/api/outreach/contacts/{email}/draft")
def api_save_draft(email: str, payload: DraftUpdate):
    row = get_contact(email)
    if not row:
        raise HTTPException(404, "Contact not found")
    new_email = (payload.email or email).strip().lower()
    if "@" not in new_email or "." not in new_email.split("@", 1)[-1]:
        raise HTTPException(400, "Enter a valid email address")
    if new_email != email.lower() and email_taken(new_email, exclude=email):
        raise HTTPException(400, "That email already exists on another contact")
    row.email = new_email
    if "@" in new_email:
        row.domain = new_email.split("@", 1)[1]
    row.subject = payload.subject.strip()
    row.body = payload.body.strip()
    row.notes = payload.notes
    if payload.subjects:
        row.subjects = "\n".join(payload.subjects)
    if row.subject and row.body and row.status in {"pending", "rejected", "failed"}:
        row.status = "drafted"
    upsert_contact(row, lookup_email=email)
    return row.to_dict()


@router.post("/api/outreach/contacts/{email}/accept")
def api_accept(email: str):
    row = get_contact(email)
    if not row:
        raise HTTPException(404, "Contact not found")
    if not row.subject or not row.body:
        raise HTTPException(400, "Draft is empty — generate or write one first")
    row.status = "accepted"
    upsert_contact(row)
    return row.to_dict()


@router.post("/api/outreach/contacts/{email}/reject")
def api_reject(email: str):
    row = get_contact(email)
    if not row:
        raise HTTPException(404, "Contact not found")
    row.status = "rejected"
    upsert_contact(row)
    return row.to_dict()


@router.post("/api/outreach/contacts/{email}/send")
def api_send(email: str):
    reload_settings()
    row = get_contact(email)
    if not row:
        raise HTTPException(404, "Contact not found")
    if not row.subject or not row.body:
        raise HTTPException(400, "Nothing to send")
    if row.status not in {"accepted", "drafted"}:
        raise HTTPException(400, "Accept the draft before sending (or keep status drafted)")
    try:
        send_gmail(to_email=row.email, subject=row.subject, body=row.body)
    except Exception as exc:  # noqa: BLE001
        row.status = "failed"
        row.error = str(exc)
        upsert_contact(row)
        raise HTTPException(500, str(exc)) from exc

    row.status = "sent"
    row.sent_at = datetime.utcnow().isoformat(timespec="seconds")
    row.error = ""
    upsert_contact(row)
    return row.to_dict()


@router.get("/api/outreach/profile")
def api_profile():
    return {"profile": load_profile()}
