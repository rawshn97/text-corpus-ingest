"""
Text Corpus Ingest: Multi-network IRC search and DCC automated retrieval engine.

Exports core orchestrators, clients, configuration models, and transfer utilities.
"""

from __future__ import annotations

from corpus_ingest.archive_fetcher import (
    ArchiveFetcher,
    MultiNetworkArchiveFetcher,
    format_search_command,
    resolve_filename_hint,
    uniquify_nick,
)
from corpus_ingest.config import (
    AppConfig,
    BehaviorConfig,
    DccConfig,
    IdentityConfig,
    NetworkConfig,
    SearchConfig,
    ServerConfig,
    load_config,
)
from corpus_ingest.dcc import (
    DccSendOffer,
    format_ctcp_dcc_send,
    format_ip_dotted,
    parse_dcc_send,
    parse_ip_integer,
    receive_dcc_send,
)
from corpus_ingest.identd import IdentDaemon
from corpus_ingest.irc_client import IrcClient
from corpus_ingest.lab_resources import fetch_lab_resource

__version__ = "0.2.0"

__all__ = [
    "AppConfig",
    "ArchiveFetcher",
    "BehaviorConfig",
    "DccConfig",
    "DccSendOffer",
    "IdentDaemon",
    "IdentityConfig",
    "IrcClient",
    "MultiNetworkArchiveFetcher",
    "NetworkConfig",
    "SearchConfig",
    "ServerConfig",
    "__version__",
    "fetch_lab_resource",
    "format_ctcp_dcc_send",
    "format_ip_dotted",
    "format_search_command",
    "load_config",
    "parse_dcc_send",
    "parse_ip_integer",
    "receive_dcc_send",
    "resolve_filename_hint",
    "uniquify_nick",
]
