"""Outbox -- the delivery stage.

Default backend ("local") writes one .txt and one .json file per draft into
an `outbox/` directory and NEVER sends or transmits anything anywhere.

An optional Gmail backend is provided, generalized from the original
create_drafts.py. It only ever creates Gmail DRAFTS (never sends), and is
gated behind `delivery.backend: gmail` in config. It requires the user's
own `credentials.json` / `token.json` (OAuth client + token), which are
gitignored and are not included in this repo. If those files are absent,
the Gmail backend raises a clear error rather than silently doing nothing.
"""
from __future__ import annotations

import base64
import html as html_lib
import json
import re
import sys
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

DEFAULT_OUTBOX_DIR = Path(__file__).resolve().parent.parent.parent / "outbox"

SCOPES = ["https://www.googleapis.com/auth/gmail.compose"]


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "draft"


# ── local backend (default, safe, no network) ───────────────────────────────

def write_local(drafts: list[dict[str, Any]], outbox_dir: str | Path | None = None) -> list[Path]:
    outbox_dir = Path(outbox_dir) if outbox_dir else DEFAULT_OUTBOX_DIR
    outbox_dir.mkdir(parents=True, exist_ok=True)

    written = []
    for i, draft in enumerate(drafts, 1):
        slug = _slugify(draft.get("name") or draft.get("org") or f"draft-{i}")
        base = outbox_dir / f"{i:02d}-{slug}"

        txt_path = base.with_suffix(".txt")
        txt_path.write_text(
            f"To: {draft.get('to_email', '')}\n"
            f"Subject: {draft.get('subject', '')}\n\n"
            f"{draft.get('body', '')}\n"
        )
        written.append(txt_path)

        json_path = base.with_suffix(".json")
        json_path.write_text(json.dumps(draft, indent=2))
        written.append(json_path)

    return written


# ── optional Gmail draft backend (never sends) ──────────────────────────────

def _load_client_secrets(creds_file: Path) -> tuple[str, str]:
    data = json.loads(creds_file.read_text())
    web = data.get("installed") or data.get("web")
    return web["client_id"], web["client_secret"]


def _build_auth_url(client_id: str) -> str:
    import urllib.parse

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": "urn:ietf:wg:oauth:2.0:oob",
        "scope": " ".join(SCOPES),
        "prompt": "consent",
        "access_type": "offline",
    }
    return "https://accounts.google.com/o/oauth2/auth?" + urllib.parse.urlencode(params)


def get_gmail_service(creds_file: Path, token_file: Path, auth_code: str | None = None):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    if not creds_file.exists():
        raise RuntimeError(
            f"Gmail backend requires {creds_file} (your own OAuth client "
            "credentials). This file is gitignored and not included in "
            "the repo -- create your own Google Cloud OAuth client and "
            "place it there, or use the default local backend instead."
        )

    creds = None
    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            client_id, client_secret = _load_client_secrets(creds_file)
            if auth_code:
                import requests as req

                r = req.post(
                    "https://oauth2.googleapis.com/token",
                    data={
                        "code": auth_code,
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "redirect_uri": "urn:ietf:wg:oauth:2.0:oob",
                        "grant_type": "authorization_code",
                    },
                    timeout=15,
                )
                r.raise_for_status()
                token = r.json()
                creds = Credentials(
                    token=token["access_token"],
                    refresh_token=token.get("refresh_token"),
                    token_uri="https://oauth2.googleapis.com/token",
                    client_id=client_id,
                    client_secret=client_secret,
                    scopes=SCOPES,
                )
            else:
                print("Gmail OAuth required. Visit this URL:", file=sys.stderr)
                print(_build_auth_url(client_id), file=sys.stderr)
                print(
                    "Then re-run with the returned code passed as auth_code.",
                    file=sys.stderr,
                )
                sys.exit(0)

        token_file.write_text(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def _body_to_html(body: str) -> str:
    paragraphs = body.split("\n\n")
    parts = [f"<p>{html_lib.escape(p.replace(chr(10), ' '))}</p>" for p in paragraphs]
    return (
        '<html><body style="font-family:sans-serif;font-size:14px;line-height:1.6;">'
        + "".join(parts)
        + "</body></html>"
    )


def create_gmail_draft(
    service,
    to_email: str,
    subject: str,
    body: str,
    attachment_path: Path | None = None,
) -> str:
    """Creates a Gmail DRAFT only -- never sends. `attachment_path`, if
    given (e.g. a resume PDF), is optional and attached if present."""
    msg = MIMEMultipart("mixed")
    msg["to"] = to_email
    msg["subject"] = subject

    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(body, "plain", "utf-8"))
    alt.attach(MIMEText(_body_to_html(body), "html", "utf-8"))
    msg.attach(alt)

    if attachment_path and Path(attachment_path).exists():
        with Path(attachment_path).open("rb") as f:
            attachment = MIMEApplication(f.read(), _subtype="pdf")
        attachment.add_header(
            "Content-Disposition", "attachment", filename=Path(attachment_path).name
        )
        msg.attach(attachment)

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    draft = service.users().drafts().create(userId="me", body={"message": {"raw": raw}}).execute()
    return draft["id"]


def write_gmail(
    drafts: list[dict[str, Any]],
    creds_file: str | Path = "credentials.json",
    token_file: str | Path = "token.json",
    attachment_path: str | Path | None = None,
) -> list[str]:
    """Pushes each draft to Gmail as a DRAFT (never sent). Requires the
    caller's own credentials.json / token.json."""
    service = get_gmail_service(Path(creds_file), Path(token_file))
    draft_ids = []
    for d in drafts:
        draft_id = create_gmail_draft(
            service, d["to_email"], d["subject"], d["body"], attachment_path
        )
        draft_ids.append(draft_id)
    return draft_ids


def run(drafts: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
    """Outbox stage entry point. Defaults to the local backend; only uses
    Gmail if explicitly configured with delivery.backend == 'gmail'."""
    delivery_cfg = config.get("delivery", {}) or {}
    backend = delivery_cfg.get("backend", "local")

    if backend == "gmail":
        draft_ids = write_gmail(
            drafts,
            creds_file=delivery_cfg.get("credentials_file", "credentials.json"),
            token_file=delivery_cfg.get("token_file", "token.json"),
            attachment_path=delivery_cfg.get("attachment_path"),
        )
        return {"backend": "gmail", "draft_ids": draft_ids, "count": len(draft_ids)}

    written = write_local(drafts, delivery_cfg.get("outbox_dir"))
    return {"backend": "local", "files": [str(p) for p in written], "count": len(drafts)}
