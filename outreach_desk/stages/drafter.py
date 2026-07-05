"""Drafter -- the personalization + quality-filter stage.

This is the crown jewel of the pipeline, ported faithfully from the
original single-purpose script and generalized:

  1. One Claude call per target writes a short, personalized "middle"
     paragraph using the sender's profile and the target's research notes,
     following the target-type's tone/framing instructions.
  2. The draft is run through two filters:
       a. `check_banned_phrases` -- a static AI-slop / corporate-speak /
          hype-phrase filter (outreach_desk/quality.py).
       b. `_validate_paragraph` -- a cheap Claude Haiku fact-check call that
          catches the model inventing an affiliation for the target that
          isn't in their approved org list. Approved orgs = the target's
          own org (generalized from "university" in the source) plus the
          sender's own affiliations (from the sender profile config, never
          hardcoded).
  3. On either failure the whole draft is retried, up to `max_retries`
     times, with the failure reason fed back into the loop.
  4. `assemble_email` slots the validated middle paragraph into a
     greeting + middle + outro built from the target-type config's
     templates.
"""
from __future__ import annotations

import re
from typing import Any

from ..config import get_env
from ..constants import (
    DRAFT_MAX_TOKENS,
    DRAFT_MODEL,
    VALIDATOR_MAX_TOKENS,
    VALIDATOR_MODEL,
)
from ..quality import check_banned_phrases


def make_subject(type_cfg: dict[str, Any], target: dict[str, Any]) -> str:
    """Build a subject line from the target-type's configured style plus
    the strongest available topic signal on the target (research notes,
    then role, then notes)."""
    prefix = (type_cfg.get("subject_style") or {}).get("prefix", "Regarding")
    topic_source = (
        target.get("research_notes") or target.get("notes") or target.get("role") or ""
    )
    first = re.split(r"[,;|]", topic_source)[0].strip()
    if first and not re.match(r"^[A-Z]{2,}", first):
        first = first[0].lower() + first[1:]
    if len(first) > 55:
        for sep in (" with ", " and ", " for ", " of "):
            idx = first.find(sep, 10)
            if idx != -1:
                first = first[:idx]
                break
    return f"{prefix} {first}".strip()


def _check_banned_phrases(text: str) -> list[str]:
    return check_banned_phrases(text)


def _validate_paragraph(
    target: dict[str, Any],
    sender_profile: dict[str, Any],
    paragraph: str,
    client: Any,
) -> tuple[bool, str]:
    """Fact-check: does the paragraph falsely attribute an affiliation to
    the TARGET that isn't in their approved org list? Uses the cheap
    validator model. Approved orgs come from the target's own record plus
    the sender's declared affiliations (never the target's)."""
    approved_orgs = [target.get("org", "")]
    approved_orgs += target.get("org_aliases", []) or []
    approved_orgs_str = ", ".join(f'"{o}"' for o in approved_orgs if o)

    sender_name = sender_profile.get("name", "the sender")
    sender_affils = sender_profile.get("affiliations", []) or []
    sender_affils_str = ", ".join(sender_affils) if sender_affils else "their own background"

    val_prompt = f"""You are a fact-checker for cold outreach emails. The email is FROM \
{sender_name} ({sender_affils_str}) TO {target.get('name', 'the recipient')} \
({target.get('role', '')} at {target.get('org', '')}).

Your ONLY job: check whether the paragraph incorrectly claims the RECIPIENT is affiliated
with a company or organization that is NOT in their approved list.

RECIPIENT'S APPROVED AFFILIATIONS: {approved_orgs_str}

Things that are ALWAYS fine to mention and must NOT be flagged:
- The sender's own affiliations: {sender_affils_str}
- Generic tools, frameworks, and technologies
- Conference or publication names
- The recipient's own known projects, products, or work by name
- Generic technical terms

ONLY flag if the paragraph claims the RECIPIENT works at or is affiliated with a specific
named organization that is NOT in their approved list.

PARAGRAPH:
{paragraph}

Reply with EXACTLY one of:
- "OK" if the paragraph does not falsely attribute any unapproved affiliation to the recipient
- "FAIL: <specific organization name that was falsely attributed>" if it does"""

    resp = client.messages.create(
        model=VALIDATOR_MODEL,
        max_tokens=VALIDATOR_MAX_TOKENS,
        messages=[{"role": "user", "content": val_prompt}],
    )
    result = resp.content[0].text.strip()
    if result.startswith("OK"):
        return True, ""
    return False, result


def generate_middle(
    target: dict[str, Any],
    sender_profile: dict[str, Any],
    type_cfg: dict[str, Any],
    max_retries: int = 3,
) -> str:
    """One Claude call per target. Writes the personalized middle
    paragraph(s), validates with the banned-phrase filter and the
    affiliation fact-checker, retrying on failure."""
    import anthropic

    api_key = get_env("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. The Drafter stage needs it to "
            "write personalized copy. Set it in .env, or run with "
            "--dry-run to skip drafting entirely."
        )
    client = anthropic.Anthropic(api_key=api_key)

    draft_instructions = type_cfg.get("draft_instructions", "").strip()
    tone = type_cfg.get("tone", "warm and genuine")

    prompt = f"""Write the body of a cold outreach email from {sender_profile.get('name', 'the sender')} \
to {target.get('name', 'the recipient')}, who is a {target.get('role', 'contact')} at {target.get('org', '')}.

RECIPIENT CONTEXT: {target.get('research_notes') or target.get('notes', '')}

SENDER PROFILE:
{sender_profile.get('bio', '')}

TONE: {tone}

TARGET-TYPE FRAMING RULES:
{draft_instructions}

OUTPUT: One or two short paragraphs separated by a blank line. Nothing else. No greeting,
no closing, no labels.

HARD RULES:
- No dashes anywhere. No em dashes, no en dashes, no hyphens as punctuation.
- No bullet points.
- Do NOT list credentials. Pick the single most relevant thing from the sender's profile.
- Do NOT say "passionate", "excited", "thrilled", "keen", "I hope", or similar filler.
- Do NOT make transparent leaps like "your work made me realize X".
- No hype words: "cutting-edge", "state-of-the-art", "groundbreaking", "revolutionary",
  "innovative", "novel approach", "paradigm", "synergy", "seamlessly", "empower",
  "at the forefront", "intersection of".
- CRITICAL: Do NOT mention any organization for the recipient that is not explicitly
  supported by the recipient context above.
- Sound like a real person who does real work, not a marketing template."""

    last_error = ""
    for attempt in range(1, max_retries + 1):
        response = client.messages.create(
            model=DRAFT_MODEL,
            max_tokens=DRAFT_MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()

        hits = _check_banned_phrases(text)
        if hits:
            last_error = f"banned phrases: {hits}"
            continue

        ok, reason = _validate_paragraph(target, sender_profile, text, client)
        if not ok:
            last_error = reason
            continue

        return text

    raise ValueError(f"Draft failed quality filter after {max_retries} attempts: {last_error}")


def assemble_email(
    target: dict[str, Any],
    sender_profile: dict[str, Any],
    type_cfg: dict[str, Any],
    email: str,
    middle: str,
) -> dict[str, Any]:
    name = target.get("name", "")
    parts = name.strip().split()
    first = parts[0] if parts else "there"
    if first.lower() in {"dr.", "dr", "prof.", "prof", "mr.", "ms.", "mx."}:
        first = parts[1] if len(parts) > 1 else first

    greeting_template = type_cfg.get("greeting_template", "Hi {first},")
    outro_template = type_cfg.get("outro_template", "Thanks for your time,\n\n{sender_name}")

    greeting = greeting_template.format(first=first.capitalize())
    outro = outro_template.format(sender_name=sender_profile.get("name", ""))

    body = f"{greeting}\n\n{middle}\n\n{outro}"

    return {
        "name": name,
        "org": target.get("org", ""),
        "to_email": email,
        "subject": make_subject(type_cfg, target),
        "body": body,
    }


def run(
    targets: list[dict[str, Any]],
    sender_profile: dict[str, Any],
    type_cfg: dict[str, Any],
    max_retries: int = 3,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Drafter stage entry point. Returns (drafts, dropped)."""
    drafts, dropped = [], []
    for target in targets:
        email = target.get("resolved_email")
        if not email:
            dropped.append({"name": target.get("name"), "reason": "no public email found"})
            continue
        try:
            middle = generate_middle(target, sender_profile, type_cfg, max_retries=max_retries)
        except Exception as e:
            dropped.append({"name": target.get("name"), "reason": str(e)})
            continue
        drafts.append(assemble_email(target, sender_profile, type_cfg, email, middle))
    return drafts, dropped
