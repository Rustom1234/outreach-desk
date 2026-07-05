"""Standalone AI-slop quality filter.

Loads data/banned_phrases.csv (phrase, category) and exposes a single
`check_banned_phrases()` function that any stage can call. Kept dependency-free
(just csv from the stdlib) so it is trivially reusable outside this pipeline.
"""
from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path

DEFAULT_BANNED_PHRASES_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "banned_phrases.csv"
)


@lru_cache(maxsize=None)
def load_banned_phrases(path: str | Path | None = None) -> list[tuple[str, str]]:
    """Return a list of (phrase, category) tuples from the CSV.

    Cached so repeated calls (once per draft attempt) don't re-read the
    file from disk.
    """
    path = Path(path) if path else DEFAULT_BANNED_PHRASES_PATH
    if not path.exists():
        raise FileNotFoundError(
            f"Banned phrases file not found at {path}. "
            "Expected data/banned_phrases.csv in the repo root."
        )
    phrases = []
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            phrase = (row.get("phrase") or "").strip()
            category = (row.get("category") or "").strip()
            if phrase:
                phrases.append((phrase, category))
    return phrases


def check_banned_phrases(text: str, path: str | Path | None = None) -> list[str]:
    """Return the list of banned phrases found in `text` (case-insensitive)."""
    lower = text.lower()
    return [phrase for phrase, _category in load_banned_phrases(path) if phrase in lower]
