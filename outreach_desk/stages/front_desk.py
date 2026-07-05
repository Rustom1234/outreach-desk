"""Front Desk -- the intake stage.

This is the stage that "pauses for user input": it loads the sender's own
profile (their resume/bio, from config), resolves which target-type config
to use (academic / recruiter / client), and loads the target list from disk.

Nothing here calls an LLM or the network -- it is pure config/data loading,
which is what makes it a clean first stage in a "watch the agents work"
visualization.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..config import load_sender_config, load_target_type_config

DEFAULT_TARGETS_PATH = (
    Path(__file__).resolve().parent.parent.parent / "data" / "targets.example.json"
)


def load_targets(path: str | Path | None = None) -> list[dict[str, Any]]:
    path = Path(path) if path else DEFAULT_TARGETS_PATH
    if not path.exists():
        raise FileNotFoundError(f"Targets file not found: {path}")
    data = json.loads(path.read_text())
    if isinstance(data, dict):
        data = data.get("targets", [])
    return data


def intake(config: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """Run the Front Desk stage.

    `config` is expected to carry at least:
      - target_type: "academic" | "recruiter" | "client"
      - sender_config_path: optional path override
      - targets_path: optional path override

    Returns (sender_profile, target_type_cfg, targets).
    """
    target_type = config.get("target_type", "academic")
    sender_profile = load_sender_config(config.get("sender_config_path"))
    target_type_cfg = load_target_type_config(target_type)
    targets = load_targets(config.get("targets_path"))

    limit = config.get("limit")
    if limit:
        targets = targets[:limit]

    return sender_profile, target_type_cfg, targets
