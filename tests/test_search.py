"""Unit tests for @search command formatting and filename hints."""

from __future__ import annotations

import pytest

from corpus_ingest.archive_fetcher import (
    format_search_command,
    resolve_filename_hint,
    uniquify_nick,
)
from corpus_ingest.config import load_config


def test_format_at_search_default() -> None:
    assert format_search_command("@search {query}", " frankenstein ") == ("@search frankenstein")


def test_format_raw_query() -> None:
    assert format_search_command("{query}", "!labbot 3") == "!labbot 3"


def test_format_rejects_empty_query() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        format_search_command("@search {query}", "   ")


def test_resolve_hint_empty_for_at_search() -> None:
    assert resolve_filename_hint("odyssey", filename_hint="", use_query_as_hint=False) == ""


def test_resolve_hint_uses_query_when_enabled() -> None:
    assert resolve_filename_hint("Odyssey", filename_hint="", use_query_as_hint=True) == "odyssey"


def test_resolve_hint_explicit_wins() -> None:
    assert (
        resolve_filename_hint("odyssey", filename_hint="Results", use_query_as_hint=True)
        == "results"
    )


def test_config_loads_at_search_defaults() -> None:
    cfg = load_config()
    assert cfg.search.command_template == "@search {query}"
    assert cfg.search.filename_hint == ""
    assert cfg.search.use_query_as_hint is False
    assert cfg.search.search_all_channels is False
    assert cfg.search.offer_timeout_sec == 180.0
    assert "SearchOok" in cfg.search.bots
    assert cfg.channels == ["#bookz"]
    assert cfg.identity.unique_nick is True


def test_uniquify_nick_fits_undernet_limit() -> None:
    nick = uniquify_nick("Rawshn")
    assert len(nick) <= 12
    assert nick.startswith("Rawshn")
    assert nick[-4:].isdigit()
