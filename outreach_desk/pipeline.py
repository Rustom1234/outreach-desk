#!/usr/bin/env python3
"""The Outreach Desk -- orchestrator + CLI.

Wires the four stages together: Front Desk -> Scout -> Drafter -> Outbox.

Usage:
    python -m outreach_desk.pipeline --target-type academic --limit 3 --dry-run
    python -m outreach_desk.pipeline --target-type recruiter --limit 2
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

from .stages import drafter, front_desk, outbox, scout

load_dotenv()


def run_pipeline(
    target_type: str = "academic",
    limit: int | None = None,
    dry_run: bool = False,
    targets_path: str | None = None,
    sender_config_path: str | None = None,
    max_retries: int = 3,
) -> dict:
    intake_config = {
        "target_type": target_type,
        "limit": limit,
        "targets_path": targets_path,
        "sender_config_path": sender_config_path,
    }

    print(f"[Front Desk] Loading sender profile, '{target_type}' config, and targets...")
    sender_profile, type_cfg, targets = front_desk.intake(intake_config)
    print(f"[Front Desk] {len(targets)} target(s) loaded.")

    print("\n[Scout] Researching targets and resolving contact emails...")
    enriched = scout.run(targets, type_cfg)
    found = sum(1 for t in enriched if t.get("resolved_email"))
    print(f"[Scout] {found}/{len(enriched)} email(s) resolved.")
    for t in enriched:
        status = t.get("resolved_email") or "NOT FOUND"
        source = f" (via {t['email_source']})" if t.get("email_source") else ""
        print(f"  - {t.get('name')}: {status}{source}")

    if dry_run:
        print("\n[Drafter] Skipped (--dry-run).")
        print("[Outbox] Skipped (--dry-run).")
        return {
            "targets": enriched,
            "drafts": [],
            "dropped": [],
            "outbox_result": None,
        }

    print("\n[Drafter] Writing and quality-checking personalized drafts...")
    drafts, dropped = drafter.run(enriched, sender_profile, type_cfg, max_retries=max_retries)
    print(f"[Drafter] {len(drafts)} draft(s) ready, {len(dropped)} dropped.")
    for d in dropped:
        print(f"  - dropped {d['name']}: {d['reason']}")

    print("\n[Outbox] Delivering drafts...")
    outbox_result = outbox.run(drafts, type_cfg)
    print(f"[Outbox] backend={outbox_result['backend']} count={outbox_result['count']}")

    return {
        "targets": enriched,
        "drafts": drafts,
        "dropped": dropped,
        "outbox_result": outbox_result,
    }


def main():
    parser = argparse.ArgumentParser(description="The Outreach Desk pipeline")
    parser.add_argument(
        "--target-type",
        choices=["academic", "recruiter", "client"],
        default="academic",
        help="Which target-type config to use (controls tone/templates/context signals).",
    )
    parser.add_argument("--limit", type=int, default=None, help="Process only the first N targets.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Research only (Front Desk + Scout); skip Claude drafting and delivery.",
    )
    parser.add_argument(
        "--targets",
        type=str,
        default=None,
        help="Path to a targets JSON file (default: data/targets.example.json).",
    )
    parser.add_argument(
        "--sender-config",
        type=str,
        default=None,
        help="Path to a sender YAML file (default: configs/sender.example.yaml).",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="Max Drafter retries per target when the quality filter fails.",
    )
    args = parser.parse_args()

    try:
        run_pipeline(
            target_type=args.target_type,
            limit=args.limit,
            dry_run=args.dry_run,
            targets_path=args.targets,
            sender_config_path=args.sender_config,
            max_retries=args.max_retries,
        )
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
