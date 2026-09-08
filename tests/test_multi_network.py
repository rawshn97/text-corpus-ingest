"""Tests for multi-network configuration and concurrent dispatch."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from corpus_ingest.archive_fetcher import (
    ArchiveFetcher,
    MultiNetworkArchiveFetcher,
    build_arg_parser,
)
from corpus_ingest.config import (
    AppConfig,
    IdentityConfig,
    NetworkConfig,
    ServerConfig,
    load_config,
)


def test_default_config_has_both_networks() -> None:
    config = load_config()
    net_names = [n.name for n in config.networks]
    assert "undernet" in net_names
    assert "irchighway" in net_names

    undernet = next(n for n in config.networks if n.name == "undernet")
    assert undernet.server.host == "irc.undernet.org"
    assert undernet.channels == ["#bookz"]
    assert "SearchOok" in undernet.search.bots
    assert "X@channels.undernet.org" in undernet.identity.x_service

    irchighway = next(n for n in config.networks if n.name == "irchighway")
    assert irchighway.server.host == "irc.irchighway.net"
    assert irchighway.channels == ["#ebooks"]
    assert "Search" in irchighway.search.bots
    assert "SearchOok" in irchighway.search.bots
    assert not irchighway.identity.x_service


def test_archive_fetcher_uses_network_config() -> None:
    config = load_config()
    irchighway = next(n for n in config.networks if n.name == "irchighway")
    fetcher = ArchiveFetcher(config, network=irchighway)
    assert fetcher.net_name == "irchighway"
    assert fetcher.server.host == "irc.irchighway.net"
    assert fetcher.channels == ["#ebooks"]
    assert fetcher.identity.x_service == ""


def test_multi_network_fetcher_stop_on_first() -> None:
    net1 = NetworkConfig(
        name="net1",
        server=ServerConfig(host="irc.net1.test"),
        channels=["#chan1"],
        identity=IdentityConfig(nick="user1"),
    )
    net2 = NetworkConfig(
        name="net2",
        server=ServerConfig(host="irc.net2.test"),
        channels=["#chan2"],
        identity=IdentityConfig(nick="user2"),
    )
    app_config = AppConfig(networks=[net1, net2])

    fetcher = MultiNetworkArchiveFetcher(app_config)
    fake_path = Path("/staging/book.epub")

    with patch.object(ArchiveFetcher, "fetch") as mock_fetch:

        def side_effect(query: str, **kwargs: object) -> Path:
            stop_event = kwargs.get("stop_event")
            if stop_event is not None and hasattr(stop_event, "is_set") and stop_event.is_set():
                raise InterruptedError("Cancelled")
            return fake_path

        mock_fetch.side_effect = side_effect
        results = fetcher.fetch("test_query", stop_on_first=True)
        assert len(results) >= 1
        assert fake_path in results


def test_multi_network_cli_args() -> None:
    parser = build_arg_parser()
    args = parser.parse_args(["-q", "babok", "--network", "irchighway", "--all-results"])
    assert args.query == "babok"
    assert args.network == "irchighway"
    assert args.all_results is True
