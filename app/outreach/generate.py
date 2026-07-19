"""Cold email generation — company first, then Kiriti, Soham-shaped."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..config import get_settings


BANNED_WORDS = (
    "passionate",
    "hardworking",
    "opportunity",
    "enthusiastic",
    "dream",
    "excited",
)

BANNED_JARGON = (
    "trust surfaces",
    "matching surfaces",
    "activity surface",
    "cohort",
    "acceptance-rate",
    "ml-ranked",
    "post-send nudge",
    "product flow",
    "junior product person",
    "0->1",
    "0 to 1",
    "1->100",
)

GOLD_TEMPLATE = """
Use this as the GOLD wording/structure for everything AFTER the company paragraph.
Swap company name / recipient. Keep this voice and sentence style almost exactly.

---
Hi Sana,

[COMPANY PARAGRAPH GOES HERE - write fresh each time, see rules below]

I am a B.Tech student at MAIT in Delhi. Right now I am a product intern at NikahForever, writing PRDs, digging through user data, and shipping features that people love. Before that, I worked on product strategy and go-to-market for a no-code ML SaaS product at Xander.

Outside of work I mostly read, and I like getting to the bottom of how and why things work, often by reverse-engineering systems or starting from the basics, and I enjoy solving hard problems and turning that into products that help people.

I would love to be considered for an APM or PM intern/full time role at Twinhealth, or for a referral to the right person or opening. I've attached my resume.

Looking forward to hearing from you soon!

Best,
Kiriti Nain
linkedin.com/in/kiritinain
---

COMPANY PARAGRAPH (the only part you invent each time):
- 2 short sentences max
- Specific to what THAT company actually does (product, users, category)
- Not generic: ban "using data and AI", "at scale", "the kind of work I want to do", "one-size-fits-all", "building something that actually changes..."
- Sound curious and concrete, like you noticed a real thing about them
- Examples of energy (don't copy): "Really liked how Happenstance is approaching X." / "I've been paying attention to how {company} handles Y for Z users."

FULL ORDER:
1) Hi FirstName,
2) Company paragraph (specific, not generic)
3) Work paragraph (MAIT + NikahForever + Xander) — match GOLD wording closely
4) Outside of work / how I think paragraph — match GOLD wording closely
5) Ask paragraph — match GOLD wording, swap company name, keep "I've attached my resume."
6) Looking forward to hearing from you soon!
7) Best, / Kiriti Nain / linkedin.com/in/kiritinain

Do NOT include any email address in the signature.
No em dashes.
No chat/coffee asks.
"""

DEFAULT_GOAL = (
    "Ask directly for a referral or APM / PM intern / full-time PM opening. No chat or call."
)


def load_profile(path: Optional[Path] = None) -> str:
    settings = get_settings()
    p = Path(path) if path else Path(settings.kiriti_profile_path)
    if not p.exists():
        return "Kiriti Nain <kitinain@gmail.com>"
    return p.read_text(encoding="utf-8", errors="ignore")


def load_resume() -> str:
    settings = get_settings()
    p = Path(settings.resume_path)
    chunks = [load_profile()]
    if p.exists():
        text = p.read_text(encoding="utf-8", errors="ignore").strip()
        if text and text not in chunks[0]:
            chunks.append("RESUME NOTES:\n" + text)
    return "\n\n".join(chunks)


def _client():
    settings = get_settings()
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    from openai import AsyncOpenAI

    return AsyncOpenAI(api_key=settings.openai_api_key), settings


async def _chat(client, settings, system: str, user: str) -> str:
    resp = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return (resp.choices[0].message.content or "").strip()


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _first_name(name: str) -> str:
    parts = (name or "").strip().split()
    return parts[0] if parts else "there"


def _strip_em_dashes(text: str) -> str:
    return text.replace("\u2014", ", ").replace("\u2013", ", ").replace("  ", " ").strip()


def _clean_subject_line(line: str) -> str:
    line = line.strip().strip('"').strip("'")
    # drop simple "1." / "1)" prefixes without regex
    if len(line) > 2 and line[0].isdigit() and line[1] in ".)-:":
        line = line[2:].strip()
    elif len(line) > 3 and line[0].isdigit() and line[1].isdigit() and line[2] in ".)-:":
        line = line[3:].strip()
    return _strip_em_dashes(line)


_SUBJECT_SMALL = frozenset(
    {"a", "an", "the", "and", "or", "but", "for", "at", "by", "to", "in", "of", "on", "with", "from"}
)
_SUBJECT_KEEP_UPPER = frozenset({"apm", "pm", "ai", "ml", "ux", "ui", "saas", "b2b", "b2c"})


def _proper_subject(line: str) -> str:
    """Title-case subject lines; keep short acronyms; never leave all-lowercase."""
    line = _clean_subject_line(line)
    if not line:
        return line
    words = line.split()
    out: list[str] = []
    for i, raw in enumerate(words):
        # preserve leading/trailing punctuation lightly
        core = raw
        prefix = suffix = ""
        while core and not core[0].isalnum():
            prefix += core[0]
            core = core[1:]
        while core and not core[-1].isalnum():
            suffix = core[-1] + suffix
            core = core[:-1]
        if not core:
            out.append(raw)
            continue
        low = core.lower()
        if low in _SUBJECT_KEEP_UPPER:
            fixed = low.upper()
        elif core.isupper() and 2 <= len(core) <= 4:
            fixed = core  # already an acronym
        elif i > 0 and low in _SUBJECT_SMALL:
            fixed = low
        else:
            fixed = core[0].upper() + core[1:]
        out.append(prefix + fixed + suffix)
    return " ".join(out)


async def generate_email(
    *,
    recipient_name: str,
    recipient_email: str,
    company: str,
    domain: str = "",
    role: str = "",
    extra_notes: str = "",
    goal: str = "",
) -> dict:
    client, settings = _client()
    about_me = load_resume()
    first = _first_name(recipient_name)
    goal = goal or DEFAULT_GOAL
    domain_hint = domain or "unknown"

    cold_system = f"""You write cold emails using a fixed gold template for Kiriti's self/work/ask.

{GOLD_TEMPLATE}

Return ONLY the email body. Plain text. No markdown. No subject."""

    cold_user = f"""Write an email from Kiriti Nain to {first} at {company}.

Recipient: {recipient_name} <{recipient_email}>
Role: {role or "unknown"}
Company domain: {domain_hint}

Goal: {goal}

About Kiriti (facts if needed):
{about_me}

Extra notes: {extra_notes or "(none)"}

Instructions:
- Follow GOLD_TEMPLATE order exactly.
- For paragraphs about work, outside-of-work, ask, and sign-off: keep the GOLD wording almost verbatim (only swap {company} / names).
- Invent ONLY the company paragraph, and make it specific to {company} ({domain_hint}). Avoid generic AI praise.
- Sign-off is ONLY:
  Best,
  Kiriti Nain
  linkedin.com/in/kiritinain
- Keep the line "I've attached my resume." in the ask paragraph.
- Do NOT put kitinain@gmail.com or any email in the body.
- No em dashes. No banned words: {", ".join(BANNED_WORDS)}. No jargon: {", ".join(BANNED_JARGON)}.

Return ONLY the email."""

    body = _strip_em_dashes(_strip_fences(await _chat(client, settings, cold_system, cold_user)))
    # never leave gmail in signature
    for junk in ("kitinain@gmail.com", "Kitinain@gmail.com"):
        body = body.replace(junk, "").replace("\n\n\n", "\n\n")
    body = body.strip()

    subjects_raw = _strip_fences(
        await _chat(
            client,
            settings,
            "Return only subject lines.",
            f"""10 subject lines. Max 7 words. Natural. No ! or em dashes.
Use proper Title Case (capitalize main words). Never all-lowercase. Never ALL CAPS shouting.
Capitalize company names and role acronyms (APM, PM).
Avoid: Quick Question, Opportunity, Let's Connect
Company: {company}
Email:
{body}
One per line.""",
        )
    )
    subjects: list[str] = []
    for line in subjects_raw.splitlines():
        line = _proper_subject(line)
        if not line or len(line.split()) > 10:
            continue
        subjects.append(line)
        if len(subjects) >= 10:
            break

    if not body:
        raise RuntimeError("Empty email body")
    if not subjects:
        subjects = [
            _proper_subject(f"Joining {company}"),
            _proper_subject(f"APM Intern at {company}"),
        ]

    return {
        "subject": subjects[0],
        "subjects": subjects,
        "body": body,
        "model": settings.openai_model,
    }
