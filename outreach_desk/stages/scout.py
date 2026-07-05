"""Scout -- the research stage.

For each target, gather whatever public context is available (pages linked
in `context_urls`, filtered by the target-type's configured context
signals) and find a contact email through a waterfall:

  0. `known_email` on the target record (already-verified, skip everything else)
  1. Scrape each `context_urls` page for a public email address
  2. Web search (DuckDuckGo HTML endpoint, no API key required)
  3. Hunter.io email-finder API (only if HUNTER_API_KEY is set; domain is
     guessed from the target's context_urls)

Every external call is wrapped so a missing API key or a network failure
degrades to "skip this step" rather than crashing the whole run -- this is
what lets `--dry-run` demos work with zero keys configured.
"""
from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from ..config import get_env

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

GENERIC_EMAIL_PREFIXES = {
    "info", "hello", "contact", "team", "admin", "support", "hr", "press",
    "media", "noreply", "no-reply", "help", "feedback", "office", "general",
    "all", "everyone", "lab", "group", "webmaster", "postmaster", "news",
    "communications", "outreach", "enquiries", "enquiry", "inquiry",
}

IMAGE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico",
    ".css", ".js", ".woff", ".ttf",
}

# Domains that belong to the search engine itself, not a target -- any
# email matched on one of these is a false positive from the search results
# page (e.g. an error/rate-limit page), not a real contact.
SEARCH_ENGINE_DOMAINS = {"duckduckgo.com", "google.com", "bing.com"}

EMAIL_RE = re.compile(
    r"[a-zA-Z0-9][a-zA-Z0-9._%+\-]*@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
    re.IGNORECASE,
)


def is_generic(email: str) -> bool:
    return email.split("@")[0].lower() in GENERIC_EMAIL_PREFIXES


# ── context gathering ──────────────────────────────────────────────────────

def gather_context(target: dict[str, Any], type_cfg: dict[str, Any]) -> str:
    """Fetch each context_url and pull out short snippets near any of the
    target-type's configured context_signals keywords. Returns a joined
    string of notes (possibly empty if nothing could be fetched)."""
    signals = [s.lower() for s in type_cfg.get("context_signals", [])]
    notes = []

    for url in target.get("context_urls", []) or []:
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "lxml")
            text = soup.get_text(" ", strip=True)
        except Exception:
            continue

        lower = text.lower()
        for signal in signals:
            idx = lower.find(signal)
            if idx != -1:
                start = max(0, idx - 80)
                end = min(len(text), idx + 160)
                notes.append(text[start:end].strip())

    return " | ".join(notes[:5])


# ── email-finding waterfall ─────────────────────────────────────────────────

def find_email(target: dict[str, Any]) -> tuple[str | None, str | None]:
    """Returns (email, source) or (None, None)."""
    if target.get("known_email"):
        return target["known_email"], "provided (known_email)"

    name = target.get("name", "")

    for url in target.get("context_urls", []) or []:
        email = _scrape_email_from_url(url, name)
        if email:
            return email, f"context page ({url})"

    email = _web_search_email(name, target.get("org", ""))
    if email:
        return email, "web search"

    hunter_key = get_env("HUNTER_API_KEY")
    if hunter_key:
        domain = _guess_domain(target)
        if domain:
            email = _hunter_person(name, domain, hunter_key)
            if email:
                return email, "Hunter.io"
    # No key, or no domain guessable -- skip gracefully, no error raised.

    return None, None


def _scrape_email_from_url(url: str, person_name: str | None = None) -> str | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=12, allow_redirects=True)
        if r.status_code != 200:
            return None

        text = r.text
        text = re.sub(r"\[at\]|\(at\)", "@", text, flags=re.IGNORECASE)
        text = re.sub(r"\[dot\]|\(dot\)", ".", text, flags=re.IGNORECASE)

        soup = BeautifulSoup(text, "lxml")
        for a in soup.find_all("a", href=True):
            if not a["href"].lower().startswith("mailto:"):
                continue
            email = a["href"][7:].split("?")[0].lower().strip()
            if "@" not in email or is_generic(email):
                continue
            if not re.match(r"^[a-z][a-z0-9._+-]*@[a-z0-9.-]+\.[a-z]{2,}$", email):
                continue
            return email

        candidates = []
        for match in EMAIL_RE.findall(text):
            email = match.lower()
            if is_generic(email):
                continue
            local, _, domain_part = email.partition("@")
            if any(domain_part.endswith(ext) or local.endswith(ext.lstrip("."))
                   for ext in IMAGE_EXTENSIONS):
                continue
            if not re.match(r"^[a-z][a-z0-9._+-]*@[a-z0-9.-]+\.[a-z]{2,}$", email):
                continue
            candidates.append(email)

        if person_name:
            parts = [p.lower() for p in re.sub(r"[^a-zA-Z\s]", "", person_name).split()]
            for email in candidates:
                local = email.split("@")[0]
                if any(part in local for part in parts if len(part) > 2):
                    return email

        return candidates[0] if candidates else None

    except Exception:
        return None


def _web_search_email(name: str, org: str = "") -> str | None:
    if not name:
        return None
    for query in [f'"{name}" "{org}" email contact', f'"{name}" "@" contact']:
        try:
            r = requests.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
                headers=HEADERS,
                timeout=10,
            )
            for match in EMAIL_RE.findall(r.text):
                email = match.lower()
                domain = email.partition("@")[2]
                if is_generic(email) or domain in SEARCH_ENGINE_DOMAINS:
                    continue
                return email
            time.sleep(1)
        except Exception:
            time.sleep(1)
    return None


def _guess_domain(target: dict[str, Any]) -> str | None:
    """Best-effort domain guess from the target's context_urls, so the
    Hunter.io lookup doesn't need a hardcoded org-name -> domain map."""
    for url in target.get("context_urls", []) or []:
        try:
            netloc = urlparse(url).netloc
        except Exception:
            continue
        if netloc:
            return netloc.replace("www.", "")
    return None


def _hunter_person(name: str, domain: str, api_key: str) -> str | None:
    parts = name.lower().split()
    if not parts:
        return None
    first, last = parts[0], parts[-1]

    try:
        r = requests.get(
            "https://api.hunter.io/v2/email-finder",
            params={
                "domain": domain,
                "first_name": first,
                "last_name": last,
                "api_key": api_key,
            },
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json().get("data", {})
            email = (data.get("email") or "").lower()
            confidence = data.get("score", 0)
            if email and confidence >= 50 and not is_generic(email):
                return email
    except Exception:
        pass
    return None


def run(targets: list[dict[str, Any]], type_cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Scout stage entry point. Enriches each target with `research_notes`,
    `resolved_email`, and `email_source`."""
    enriched = []
    for target in targets:
        t = dict(target)
        t["research_notes"] = gather_context(t, type_cfg)
        email, source = find_email(t)
        t["resolved_email"] = email
        t["email_source"] = source
        enriched.append(t)
    return enriched
