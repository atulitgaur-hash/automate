from __future__ import annotations

import logging
from typing import Optional

import httpx

from app.companies import LEVER_COMPANIES
from app.db import Listing
from app.normalize import normalize

log = logging.getLogger(__name__)

BASE = "https://api.lever.co/v0/postings/{token}"


async def fetch_lever(
    client: httpx.AsyncClient,
    companies: Optional[list[str]] = None,
) -> tuple[list[Listing], list[str]]:
    listings: list[Listing] = []
    errors: list[str] = []
    tokens = companies or LEVER_COMPANIES

    for token in tokens:
        url = BASE.format(token=token)
        try:
            resp = await client.get(url, params={"mode": "json"}, timeout=20.0)
            if resp.status_code == 404:
                continue
            if resp.status_code != 200:
                errors.append(f"lever/{token}: HTTP {resp.status_code}")
                continue
            jobs = resp.json()
            if not isinstance(jobs, list):
                continue
            company_name = token.replace("-", " ").title()
            for job in jobs:
                cats = job.get("categories") or {}
                location = cats.get("location") or ""
                if isinstance(location, list):
                    location = ", ".join(location)
                item = normalize(
                    title=job.get("text") or "",
                    company=company_name,
                    location=location or "",
                    description=job.get("descriptionPlain") or job.get("description") or "",
                    url=job.get("hostedUrl") or job.get("applyUrl") or "",
                    source="lever",
                    posted_date=str(job.get("createdAt")) if job.get("createdAt") else None,
                    salary=_salary_from_lever(job),
                )
                if item:
                    listings.append(item)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"lever/{token}: {exc}")
            log.warning("Lever fetch failed for %s: %s", token, exc)

    return listings, errors


def _salary_from_lever(job: dict) -> Optional[str]:
    salary = job.get("salaryRange") or job.get("salary_range")
    if not salary:
        return None
    if isinstance(salary, dict):
        lo = salary.get("min") or salary.get("minValue")
        hi = salary.get("max") or salary.get("maxValue")
        currency = salary.get("currency") or ""
        if lo or hi:
            return f"{currency} {lo or '?'}–{hi or '?'}".strip()
    return str(salary)
