"""Tests for local lab asset resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from corpus_ingest.lab_resources import DEFAULT_LAB_DIR, fetch_lab_resource


def test_fetch_by_exact_filename() -> None:
    path = fetch_lab_resource("SearchResults_fixed.txt")
    assert path == DEFAULT_LAB_DIR / "SearchResults_fixed.txt"
    assert path.is_file()
    assert "LAB_OK" in path.read_text(encoding="utf-8")


def test_fetch_by_stem() -> None:
    path = fetch_lab_resource("SearchResults_business_analysis")
    assert path.name == "SearchResults_business_analysis.txt"


def test_fetch_by_unique_substring() -> None:
    path = fetch_lab_resource("fixed")
    assert path.name == "SearchResults_fixed.txt"


def test_rejects_empty() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        fetch_lab_resource("  ")


def test_rejects_path_traversal() -> None:
    with pytest.raises(ValueError, match="alphanumeric|path"):
        fetch_lab_resource("../secrets")


def test_unknown_id(tmp_path: Path) -> None:
    (tmp_path / "only.txt").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="unknown lab resource"):
        fetch_lab_resource("missing", lab_dir=tmp_path)


def test_ambiguous_substring(tmp_path: Path) -> None:
    (tmp_path / "alpha_one.txt").write_text("a", encoding="utf-8")
    (tmp_path / "alpha_two.txt").write_text("b", encoding="utf-8")
    with pytest.raises(ValueError, match="ambiguous"):
        fetch_lab_resource("alpha", lab_dir=tmp_path)
