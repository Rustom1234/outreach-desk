"""Config loading for The Outreach Desk.

Two kinds of YAML config:
  - a target-type config (configs/academic.yaml, recruiter.yaml, client.yaml)
    that controls tone, subject style, templates, and what context signals
    the Scout stage looks for.
  - a sender config (configs/sender.example.yaml) that describes the person
    sending the outreach -- name, bio, affiliations, skills. This replaces
    a hardcoded profile string with something anyone can swap out.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIGS_DIR = REPO_ROOT / "configs"

VALID_TARGET_TYPES = {"academic", "recruiter", "client"}


def load_yaml(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open() as f:
        data = yaml.safe_load(f) or {}
    return data


def load_target_type_config(target_type: str) -> dict[str, Any]:
    if target_type not in VALID_TARGET_TYPES:
        raise ValueError(
            f"Unknown target type '{target_type}'. Valid options: "
            f"{sorted(VALID_TARGET_TYPES)}"
        )
    path = CONFIGS_DIR / f"{target_type}.yaml"
    cfg = load_yaml(path)
    cfg.setdefault("target_type", target_type)
    return cfg


def load_sender_config(path: str | Path | None = None) -> dict[str, Any]:
    path = Path(path) if path else CONFIGS_DIR / "sender.example.yaml"
    return load_yaml(path)


def get_env(name: str, default: str = "") -> str:
    """Read an env var, returning a default rather than raising.

    Callers should check truthiness and degrade gracefully (skip the
    feature, print a clear message) rather than crash when a key is
    missing -- this is what lets --dry-run work with zero API keys.
    """
    return os.getenv(name, default)
