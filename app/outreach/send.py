"""Send outreach emails via Gmail SMTP with PDF resume attached."""

from __future__ import annotations

import os
import smtplib
import ssl
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import httpx

from ..config import ROOT, get_settings


def _drive_download_url(file_id: str) -> str:
    return f"https://drive.google.com/uc?export=download&id={file_id}"


def ensure_resume_pdf() -> Path:
    """Return local PDF path, downloading from Google Drive once if missing."""
    settings = get_settings()
    path = Path(settings.resume_pdf_path)
    bundled = ROOT / "assets" / "Kiriti_Nain_Resume.pdf"

    # Prefer any existing valid PDF (tracked asset works on Vercel read-only FS)
    for candidate in (bundled, path):
        if candidate.exists() and candidate.stat().st_size > 1000:
            head = candidate.read_bytes()[:5]
            if head.startswith(b"%PDF"):
                return candidate

    # Missing — download. On Vercel write only under /tmp.
    if os.getenv("VERCEL") == "1":
        path = Path("/tmp/Kiriti_Nain_Resume.pdf")

    file_id = (settings.resume_drive_file_id or "").strip()
    if not file_id:
        raise RuntimeError(
            f"Resume PDF not found at {path}. Set RESUME_PDF_PATH or RESUME_DRIVE_FILE_ID."
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    url = _drive_download_url(file_id)
    with httpx.Client(follow_redirects=True, timeout=60.0) as client:
        resp = client.get(url)
        # Google sometimes returns an HTML confirm page for large files
        if "text/html" in resp.headers.get("content-type", "") and "confirm=" in resp.text:
            token = None
            for part in resp.text.split("confirm="):
                if not part:
                    continue
                token = part.split("&")[0].split('"')[0]
                if token:
                    break
            if token:
                resp = client.get(_drive_download_url(file_id) + f"&confirm={token}")
        resp.raise_for_status()
        data = resp.content

    if not data.startswith(b"%PDF"):
        raise RuntimeError(
            "Downloaded file is not a PDF. Make sure the Drive link is shared "
            '("Anyone with the link") and points to the PDF file.'
        )

    path.write_bytes(data)
    return path


def send_gmail(*, to_email: str, subject: str, body: str) -> None:
    settings = get_settings()
    if not settings.gmail_address or not settings.gmail_app_password:
        raise RuntimeError(
            "Set GMAIL_ADDRESS and GMAIL_APP_PASSWORD "
            "(Google Account → Security → App passwords)"
        )

    pdf_path = ensure_resume_pdf()

    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = f"Kiriti Nain <{settings.gmail_address}>"
    msg["To"] = to_email
    msg["Reply-To"] = settings.gmail_address

    msg.attach(MIMEText(body, "plain", "utf-8"))

    pdf_bytes = pdf_path.read_bytes()
    attachment = MIMEApplication(pdf_bytes, _subtype="pdf")
    attachment.add_header(
        "Content-Disposition",
        "attachment",
        filename="Kiriti_Nain_Resume.pdf",
    )
    msg.attach(attachment)

    context = ssl.create_default_context()
    with smtplib.SMTP(settings.gmail_smtp_host, settings.gmail_smtp_port, timeout=30) as server:
        server.starttls(context=context)
        server.login(settings.gmail_address, settings.gmail_app_password)
        server.sendmail(settings.gmail_address, [to_email], msg.as_string())
