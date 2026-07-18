from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from .config import get_settings
from .db import Listing
from .normalize import location_relevance

# Core role/signal terms — always scored even without a resume file
CORE_TERMS = {
    "product manager",
    "associate product manager",
    "apm",
    "product intern",
    "product management",
    "roadmap",
    "prioritization",
    "user research",
    "analytics",
    "metrics",
    "kpi",
    "okrs",
    "a/b testing",
    "experimentation",
    "prd",
    "stakeholder",
    "go-to-market",
    "gtm",
    "user stories",
    "agile",
    "scrum",
    "sql",
    "figma",
    "mixpanel",
    "amplitude",
    "fresher",
    "intern",
    "graduate",
    "trainee",
}


def _tokenize_skills(text: str) -> set[str]:
    text = text.lower()
    # Keep multi-word phrases from CORE first, then single tokens
    phrases = set()
    for term in CORE_TERMS:
        if " " in term and term in text:
            phrases.add(term)
    tokens = set(re.findall(r"[a-z][a-z0-9+/#.-]{1,}", text))
    # Drop ultra-common stopwords
    stop = {
        "the", "and", "for", "with", "you", "your", "our", "are", "this", "that",
        "from", "will", "have", "been", "also", "into", "about", "their", "they",
        "role", "team", "work", "working", "experience", "years", "ability",
    }
    return (tokens - stop) | phrases | CORE_TERMS


@lru_cache
def resume_skills() -> frozenset[str]:
    settings = get_settings()
    path = Path(settings.resume_path)
    text = ""
    if path.exists():
        text = path.read_text(encoding="utf-8", errors="ignore")
    return frozenset(_tokenize_skills(text) | CORE_TERMS)


def score_listing(listing: Listing) -> float:
    """Keyword-overlap fit score in 0–100.

    Weights: title match strength + skill overlap in description + Delhi/India boost.
    """
    skills = resume_skills()
    blob = f"{listing.title} {listing.description}".lower()
    title = listing.title.lower()

    # Title role strength (intern/APM preferred over plain PM)
    title_score = 0.0
    if re.search(r"associate product manager", title) or (
        re.search(r"\bapm\b", title)
        and not re.search(r"performance|monitoring|observability|engineer", title)
    ):
        title_score = 38.0
    elif re.search(r"product manager\s+(intern|trainee|graduate|associate)", title):
        title_score = 38.0
    elif re.search(r"\b(pm|product)\s+(intern|trainee)\b", title):
        title_score = 36.0
    elif re.search(r"\bjunior product manager\b", title):
        title_score = 32.0
    elif re.search(r"\bproduct (associate|analyst)\b", title):
        title_score = 24.0
    elif re.search(r"\bproduct managers?\b", title):
        title_score = 18.0  # India plain PM — useful but not ideal fresher match
    else:
        title_score = 12.0

    # Skill overlap (cap contribution)
    hits = sum(1 for s in skills if len(s) > 2 and s in blob)
    # Normalize: ~12 hits → full skill points
    skill_score = min(45.0, (hits / 12.0) * 45.0)

    loc_score = location_relevance(listing.location, listing.description) * 20.0

    # Small bonus when JD explicitly says fresher / 0-2 years
    yoe_bonus = 0.0
    if re.search(
        r"\b(fresher|0\s*[-–—to]+\s*[12]\s*years?|1\s*[-–—to]+\s*2\s*years?|"
        r"up\s*to\s*2\s*years?|entry[- ]level|intern)\b",
        blob,
    ):
        yoe_bonus = 5.0

    return round(min(100.0, title_score + skill_score + loc_score + yoe_bonus), 1)
