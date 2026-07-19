"""Excel-backed store for outreach contacts + drafts (no SQLite)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from ..config import ROOT, get_settings
from .excel import parse_excel

COLUMNS = [
    "email",
    "name",
    "company",
    "domain",
    "sheet",
    "status",
    "subject",
    "body",
    "notes",
    "error",
    "subjects",
    "updated_at",
    "sent_at",
]

STATUSES = ("pending", "drafted", "accepted", "rejected", "sent", "failed")


@dataclass
class Contact:
    email: str
    name: str = ""
    company: str = ""
    domain: str = ""
    sheet: str = ""
    status: str = "pending"
    subject: str = ""
    body: str = ""
    notes: str = ""
    error: str = ""
    subjects: str = ""  # newline-separated subject options
    updated_at: str = ""
    sent_at: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["subject_options"] = [s for s in (self.subjects or "").split("\n") if s.strip()]
        return d


def tracker_path() -> Path:
    settings = get_settings()
    raw = getattr(settings, "outreach_tracker_path", "") or str(ROOT / "data" / "outreach_tracker.xlsx")
    return Path(raw)


def _empty_df() -> pd.DataFrame:
    return pd.DataFrame(columns=COLUMNS)


def _load_df() -> pd.DataFrame:
    path = tracker_path()
    if not path.exists():
        return _empty_df()
    df = pd.read_excel(path, dtype=str).fillna("")
    for col in COLUMNS:
        if col not in df.columns:
            df[col] = ""
    return df[COLUMNS]


def _save_df(df: pd.DataFrame) -> None:
    path = tracker_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    df = df.reindex(columns=COLUMNS).fillna("")
    df.to_excel(path, index=False)


def _row_to_contact(row: pd.Series) -> Contact:
    return Contact(**{c: str(row.get(c, "") or "") for c in COLUMNS})


def sync_from_source() -> dict:
    """Merge source Excel contacts into the tracker workbook."""
    parsed = parse_excel()
    df = _load_df()
    by_email = {str(r.email).lower(): i for i, r in df.iterrows()} if len(df) else {}
    now = datetime.utcnow().isoformat(timespec="seconds")
    inserted = 0
    updated = 0

    rows = df.to_dict("records") if len(df) else []
    index = {str(r["email"]).lower(): i for i, r in enumerate(rows)}

    for c in parsed:
        email = c.email.lower()
        if email in index:
            i = index[email]
            rows[i]["name"] = c.name
            rows[i]["company"] = c.company
            rows[i]["domain"] = c.domain
            rows[i]["sheet"] = c.sheet
            rows[i]["updated_at"] = now
            updated += 1
        else:
            rows.append(
                {
                    "email": email,
                    "name": c.name,
                    "company": c.company,
                    "domain": c.domain,
                    "sheet": c.sheet,
                    "status": "pending",
                    "subject": "",
                    "body": "",
                    "notes": "",
                    "error": "",
                    "subjects": "",
                    "updated_at": now,
                    "sent_at": "",
                }
            )
            index[email] = len(rows) - 1
            inserted += 1

    out = pd.DataFrame(rows).reindex(columns=COLUMNS).fillna("")
    _save_df(out)
    companies = out["company"].nunique() if len(out) else 0
    return {
        "inserted": inserted,
        "updated": updated,
        "total": len(out),
        "companies": int(companies),
        "tracker": str(tracker_path()),
    }


def list_companies() -> list[dict]:
    df = _load_df()
    if df.empty:
        return []
    out = []
    for company, g in df.groupby("company", sort=False):
        counts = g["status"].value_counts().to_dict()
        out.append(
            {
                "company": company,
                "total": int(len(g)),
                "pending": int(counts.get("pending", 0)),
                "drafted": int(counts.get("drafted", 0)),
                "accepted": int(counts.get("accepted", 0)),
                "rejected": int(counts.get("rejected", 0)),
                "sent": int(counts.get("sent", 0)),
                "failed": int(counts.get("failed", 0)),
            }
        )
    out.sort(key=lambda x: (-x["total"], x["company"].lower()))
    return out


def list_contacts(
    *,
    company: str | None = None,
    status: str | None = None,
    q: str = "",
    limit: int = 200,
) -> list[Contact]:
    df = _load_df()
    if df.empty:
        return []
    if company:
        df = df[df["company"] == company]
    if status and status != "all":
        df = df[df["status"] == status]
    if q:
        ql = q.lower()
        mask = (
            df["name"].str.lower().str.contains(ql, na=False)
            | df["email"].str.lower().str.contains(ql, na=False)
            | df["company"].str.lower().str.contains(ql, na=False)
        )
        df = df[mask]
    df = df.sort_values(["company", "name"]).head(limit)
    return [_row_to_contact(r) for _, r in df.iterrows()]


def get_contact(email: str) -> Optional[Contact]:
    df = _load_df()
    if df.empty:
        return None
    hit = df[df["email"].str.lower() == email.lower()]
    if hit.empty:
        return None
    return _row_to_contact(hit.iloc[0])


def upsert_contact(contact: Contact, *, lookup_email: Optional[str] = None) -> Contact:
    """Persist a contact. If lookup_email differs from contact.email, rename that row."""
    df = _load_df()
    contact.email = (contact.email or "").strip().lower()
    contact.updated_at = datetime.utcnow().isoformat(timespec="seconds")
    row = asdict(contact)
    key = (lookup_email or contact.email).strip().lower()
    if df.empty:
        df = pd.DataFrame([row], columns=COLUMNS)
    else:
        mask = df["email"].str.lower() == key
        if mask.any():
            idx = df.index[mask][0]
            for k, v in row.items():
                df.at[idx, k] = v
        else:
            df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    _save_df(df)
    return contact


def email_taken(email: str, *, exclude: str = "") -> bool:
    df = _load_df()
    if df.empty:
        return False
    e = email.strip().lower()
    ex = exclude.strip().lower()
    hit = df[df["email"].str.lower() == e]
    if hit.empty:
        return False
    if ex and hit.iloc[0]["email"].lower() == ex:
        return False
    return True
