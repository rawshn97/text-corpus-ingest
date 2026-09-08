"""Resolve named assets from the closed lab staging catalog.

Lab resources live under ``staging/lab/`` (synthetic fixtures for client
validation). This module does not open IRC or DCC connections.
"""

from __future__ import annotations

import re
from pathlib import Path

from corpus_ingest.config import REPO_ROOT

DEFAULT_LAB_DIR = REPO_ROOT / "staging" / "lab"

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def fetch_lab_resource(
    resource_id: str,
    *,
    lab_dir: Path | None = None,
) -> Path:
    """Return the path to a staged lab asset by name or ID.

    Matching order:
      1. Exact filename under ``lab_dir``
      2. Exact stem (filename without suffix)
      3. Unique case-insensitive substring match on name or stem

    Raises:
      ValueError: empty / unsafe id, or zero / ambiguous matches.
      FileNotFoundError: ``lab_dir`` does not exist.
    """
    rid = (resource_id or "").strip()
    if not rid:
        raise ValueError("resource_id must be a non-empty name or ID")
    if not _SAFE_ID.match(rid):
        raise ValueError(
            "resource_id must be alphanumeric with optional . _ - "
            f"(got {resource_id!r})"
        )
    if "/" in rid or "\\" in rid or ".." in rid:
        raise ValueError(f"resource_id must not contain path separators: {resource_id!r}")

    root = (lab_dir or DEFAULT_LAB_DIR).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"lab directory not found: {root}")

    files = [p for p in root.iterdir() if p.is_file()]
    if not files:
        raise ValueError(f"no lab resources in {root}")

    # Exact filename
    exact = root / rid
    if exact.is_file():
        return exact

    # Exact stem
    stem_hits = [p for p in files if p.stem == rid]
    if len(stem_hits) == 1:
        return stem_hits[0]
    if len(stem_hits) > 1:
        names = ", ".join(sorted(p.name for p in stem_hits))
        raise ValueError(f"ambiguous resource_id {rid!r}: {names}")

    # Case-insensitive unique substring on name or stem
    needle = rid.lower()
    fuzzy = [
        p
        for p in files
        if needle in p.name.lower() or needle in p.stem.lower()
    ]
    if len(fuzzy) == 1:
        return fuzzy[0]
    if len(fuzzy) > 1:
        names = ", ".join(sorted(p.name for p in fuzzy))
        raise ValueError(f"ambiguous resource_id {rid!r}: {names}")

    available = ", ".join(sorted(p.name for p in files)) or "(none)"
    raise ValueError(
        f"unknown lab resource {rid!r}; available: {available}"
    )
