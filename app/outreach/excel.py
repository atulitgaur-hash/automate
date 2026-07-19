"""Parse outreach contacts from the System 2 Excel workbook."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd

from ..config import ROOT

DEFAULT_EXCEL = ROOT / "data" / "Copy of System 2.xlsx"

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

SKIP_DOMAINS = {
    "gmail.com",
    "yahoo.com",
    "outlook.com",
    "hotmail.com",
    "alumni.stanford.edu",
    "ext.",  # handled below
}

DOMAIN_MAP = {
    "oyorooms.com": "OYO",
    "pw.live": "Physics Wallah",
    "makemytrip.com": "MakeMyTrip",
    "nexxbase.com": "Noise",
    "imaginemarketingindia.com": "boAt",
    "eightfold.ai": "Eightfold",
    "unifyapps.com": "Unify",
    "getvisitapp.com": "Visit App",
    "getcerta.com": "Certa",
    "invictusdata.ai": "Invictus Data",
    "meesho.com": "Meesho",
    "phonepe.com": "PhonePe",
    "swiggy.in": "Swiggy",
    "zeptonow.com": "Zepto",
    "flipkart.com": "Flipkart",
    "getphyllo.com": "Phyllo",
    "groww.in": "Groww",
    "nykaa.com": "Nykaa",
    "navi.com": "Navi",
    "myntra.com": "Myntra",
    "airbnb.com": "Airbnb",
    "emergent.sh": "Emergent",
    "stablemoney.in": "Stable Money",
    "atlan.com": "Atlan",
    "cred.club": "CRED",
    "leena.ai": "Leena AI",
    "urbancompany.com": "Urban Company",
    "wishlink.com": "Wishlink",
    "apollo247.com": "Apollo 24|7",
    "dezerv.in": "Dezerv",
    "expediagroup.com": "Expedia Group",
    "fnz.com": "FNZ",
    "pinelabs.com": "Pine Labs",
    "ema.co": "Ema",
    "noon.com": "Noon",
    "redbus.in": "redBus",
    "reddit.com": "Reddit",
    "olacabs.com": "Ola",
    "skydo.com": "Skydo",
    "sliceit.com": "Slice",
    "cricbuzz.com": "Cricbuzz",
    "leapfinance.com": "Leap Finance",
    "changejar.app": "Changejar",
    "slicebank.com": "Slice Bank",
    "mamaearth.in": "Mamaearth",
    "snapmint.com": "Snapmint",
    "blinkit.com": "Blinkit",
    "honasa.in": "Honasa",
    "razorpay.com": "Razorpay",
    "cars24.com": "Cars24",
    "tide.co": "Tide",
    "wayfair.com": "Wayfair",
    "zomato.com": "Zomato",
    "gartner.com": "Gartner",
}

SHEET_COMPANY = {
    "Noon": "Noon",
    "oyo": "OYO",
    "PW": "Physics Wallah",
    "Snapmint": "Snapmint",
    "Zomato": "Zomato",
    "Nykaa": "Nykaa",
    "Wishlink": "Wishlink",
    "MMT": "MakeMyTrip",
    "Gartner": "Gartner",
    "Eightfold": "Eightfold",
    "Noise": "Noise",
    "Boat": "boAt",
    "unify": "Unify",
}


@dataclass
class ParsedContact:
    email: str
    name: str
    company: str
    domain: str
    sheet: str


def _company_from_domain(domain: str) -> str:
    d = domain.lower()
    if d in DOMAIN_MAP:
        return DOMAIN_MAP[d]
    base = d.split(".")[0]
    return base.replace("-", " ").title()


def _parse_name(email: str, raw: str) -> str:
    m = re.match(r"^\s*([^<]+?)\s*<\s*" + re.escape(email) + r"\s*>", raw, re.I)
    if m:
        return m.group(1).strip().title()
    local = email.split("@")[0]
    parts = re.split(r"[._+\-]+", local)
    parts = [p for p in parts if p and not p.isdigit()]
    if not parts:
        return local
    return " ".join(p.capitalize() for p in parts[:3])


def _skip_domain(domain: str) -> bool:
    d = domain.lower()
    if d in SKIP_DOMAINS:
        return True
    if d.startswith("ext.") or d.endswith(".ext"):
        return True
    if "alumni." in d:
        return True
    return False


def parse_excel(path: Optional[Path] = None) -> list[ParsedContact]:
    if path is None:
        from ..config import get_settings

        settings = get_settings()
        path = Path(settings.outreach_excel_path) if settings.outreach_excel_path else DEFAULT_EXCEL
    else:
        path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Excel not found: {path}")

    xl = pd.ExcelFile(path)
    contacts: list[ParsedContact] = []

    for sheet in xl.sheet_names:
        df = pd.read_excel(path, sheet_name=sheet)
        col = df.columns[0]
        for raw in df[col].tolist():
            if pd.isna(raw):
                continue
            text = str(raw).strip().rstrip(",")
            for email in EMAIL_RE.findall(text):
                email_l = email.lower()
                domain = email_l.split("@", 1)[1]
                if _skip_domain(domain) and sheet not in SHEET_COMPANY:
                    continue
                if sheet in SHEET_COMPANY:
                    company = SHEET_COMPANY[sheet]
                else:
                    if _skip_domain(domain):
                        continue
                    company = _company_from_domain(domain)
                contacts.append(
                    ParsedContact(
                        email=email_l,
                        name=_parse_name(email_l, text),
                        company=company,
                        domain=domain,
                        sheet=sheet,
                    )
                )

    # Deduplicate by email (keep first occurrence)
    seen: set[str] = set()
    unique: list[ParsedContact] = []
    for c in contacts:
        if c.email in seen:
            continue
        seen.add(c.email)
        unique.append(c)
    return unique


def company_summary(contacts: list[ParsedContact]) -> list[dict]:
    buckets: dict[str, list[ParsedContact]] = defaultdict(list)
    for c in contacts:
        buckets[c.company].append(c)
    rows = []
    for company, items in sorted(buckets.items(), key=lambda x: (-len(x[1]), x[0].lower())):
        domains = sorted({i.domain for i in items})
        rows.append(
            {
                "company": company,
                "count": len(items),
                "domains": domains,
                "sheets": sorted({i.sheet for i in items}),
            }
        )
    return rows
