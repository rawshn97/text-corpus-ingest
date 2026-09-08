"""Load IRC ingest configuration from YAML + environment overrides."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO_ROOT / "config" / "irc.yaml"
LOCAL_CONFIG = REPO_ROOT / "config" / "irc.local.yaml"


@dataclass
class ServerConfig:
    host: str
    port: int = 6667
    use_tls: bool = False
    password: str | None = None


@dataclass
class IdentityConfig:
    nick: str
    username: str = "youruser"
    realname: str = "Example IRC Client"
    # Append digits so hung prior sessions do not steal the nick (433).
    unique_nick: bool = True
    # Undernet CService (X) login. Empty skips LOGIN.
    x_service: str = "X@channels.undernet.org"
    x_username: str | None = None
    x_password: str | None = None


@dataclass
class SearchConfig:
    command_template: str = "@search {query}"
    filename_hint: str = ""
    use_query_as_hint: bool = False
    offer_timeout_sec: float = 180.0
    # When true, emit the search PRIVMSG on every configured channel.
    search_all_channels: bool = True
    # Pause after JOIN confirms before sending @search (bots often ignore instant flood).
    post_join_delay_sec: float = 8.0
    # Also PRIVMSG these nicks (channel @search is often ignored by new clients).
    bots: list[str] = field(default_factory=list)


@dataclass
class DccConfig:
    auto_accept: bool = True
    auto_resume: bool = False
    bind_address: str = ""
    connect_timeout_sec: float = 30.0


@dataclass
class BehaviorConfig:
    connect_timeout_sec: float = 30.0
    read_timeout_sec: float = 60.0
    quit_after_download: bool = True
    # Append a suffix and retry NICK when the server reports nick-in-use (433).
    nick_retry: int = 5
    # Try to bind TCP 113 and answer ident queries (usually needs root / port forward).
    identd: bool = True


@dataclass
class NetworkConfig:
    name: str
    server: ServerConfig
    channels: list[str]
    identity: IdentityConfig
    search: SearchConfig = field(default_factory=SearchConfig)


@dataclass
class AppConfig:
    networks: list[NetworkConfig] = field(default_factory=list)
    server: ServerConfig | None = None
    identity: IdentityConfig | None = None
    channels: list[str] = field(default_factory=list)
    search: SearchConfig = field(default_factory=SearchConfig)
    dcc: DccConfig = field(default_factory=DccConfig)
    staging_dir: Path = field(default_factory=lambda: REPO_ROOT / "staging")
    behavior: BehaviorConfig = field(default_factory=BehaviorConfig)

    def __post_init__(self) -> None:
        if not self.networks and self.server is not None:
            ident = self.identity or IdentityConfig(nick="Rawshn")
            net = NetworkConfig(
                name="default",
                server=self.server,
                channels=self.channels or ["#bookz"],
                identity=ident,
                search=self.search,
            )
            self.networks = [net]
        elif self.networks:
            if self.server is None:
                self.server = self.networks[0].server
            if self.identity is None:
                self.identity = self.networks[0].identity
            if not self.channels:
                self.channels = self.networks[0].channels
            if not self.search.bots and self.networks[0].search.bots:
                self.search = self.networks[0].search


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise TypeError(f"Config root must be a mapping: {path}")
    return data


def load_config(config_path: Path | None = None) -> AppConfig:
    load_dotenv(REPO_ROOT / ".env")

    base_path = config_path or DEFAULT_CONFIG
    raw = _load_yaml(base_path)
    if config_path is None:
        raw = _deep_merge(raw, _load_yaml(LOCAL_CONFIG))
    else:
        local_override = base_path.with_name(f"{base_path.stem}.local{base_path.suffix}")
        raw = _deep_merge(raw, _load_yaml(local_override))

    server_raw = raw.get("server") or {}
    identity_raw = raw.get("identity") or {}
    search_raw = raw.get("search") or {}
    dcc_raw = raw.get("dcc") or {}
    paths_raw = raw.get("paths") or {}
    behavior_raw = raw.get("behavior") or {}

    root_nick = os.getenv("IRC_NICK") or identity_raw.get("nick") or "YourNick"
    root_password = os.getenv("IRC_SERVER_PASSWORD") or server_raw.get("password")
    root_x_password = (
        os.getenv("IRC_X_PASSWORD") or os.getenv("IRC_PASSWORD") or identity_raw.get("x_password")
    )
    root_x_username = os.getenv("IRC_X_USER") or identity_raw.get("x_username") or root_nick

    staging = os.getenv("STAGING_DIR") or paths_raw.get("staging_dir") or "staging"
    staging_path = Path(staging)
    if not staging_path.is_absolute():
        staging_path = REPO_ROOT / staging_path

    networks_raw = raw.get("networks")
    networks: list[NetworkConfig] = []

    if networks_raw and isinstance(networks_raw, list):
        for idx, net_dict in enumerate(networks_raw):
            if not isinstance(net_dict, dict):
                continue
            net_name = str(net_dict.get("name") or f"network_{idx}")
            net_server_raw = net_dict.get("server") or server_raw
            net_identity_raw = net_dict.get("identity") or identity_raw
            net_search_raw = net_dict.get("search") or search_raw
            net_channels = [str(c) for c in (net_dict.get("channels") or raw.get("channels") or [])]
            if not net_channels:
                continue

            net_nick = str(net_identity_raw.get("nick") or root_nick)
            net_user = str(net_identity_raw.get("username") or net_nick)
            net_real = str(
                net_identity_raw.get("realname")
                or identity_raw.get("realname")
                or "Example IRC Client"
            )
            net_uniq = bool(
                net_identity_raw.get("unique_nick", identity_raw.get("unique_nick", True))
            )
            net_x_serv = str(
                net_identity_raw.get("x_service")
                if "x_service" in net_identity_raw
                else identity_raw.get("x_service", "X@channels.undernet.org")
            )
            net_x_user = net_identity_raw.get("x_username") or root_x_username
            net_x_pass = net_identity_raw.get("x_password") or root_x_password

            net_server = ServerConfig(
                host=str(net_server_raw.get("host") or "irc.example.net"),
                port=int(net_server_raw.get("port") or 6667),
                use_tls=bool(net_server_raw.get("use_tls") or False),
                password=str(root_password)
                if root_password
                else (
                    str(net_server_raw.get("password")) if net_server_raw.get("password") else None
                ),
            )
            net_ident = IdentityConfig(
                nick=net_nick,
                username=net_user,
                realname=net_real,
                unique_nick=net_uniq,
                x_service=net_x_serv,
                x_username=str(net_x_user) if net_x_user else None,
                x_password=str(net_x_pass) if net_x_pass else None,
            )
            net_search = SearchConfig(
                command_template=str(
                    net_search_raw.get("command_template")
                    or search_raw.get("command_template")
                    or "@search {query}"
                ),
                filename_hint=str(
                    net_search_raw.get("filename_hint") or search_raw.get("filename_hint") or ""
                ),
                use_query_as_hint=bool(
                    net_search_raw.get(
                        "use_query_as_hint", search_raw.get("use_query_as_hint", False)
                    )
                ),
                offer_timeout_sec=float(
                    net_search_raw.get("offer_timeout_sec")
                    or search_raw.get("offer_timeout_sec")
                    or 180
                ),
                search_all_channels=bool(
                    net_search_raw.get(
                        "search_all_channels",
                        search_raw.get("search_all_channels", False),
                    )
                ),
                post_join_delay_sec=float(
                    net_search_raw.get("post_join_delay_sec")
                    or search_raw.get("post_join_delay_sec")
                    or 8
                ),
                bots=[str(b) for b in (net_search_raw.get("bots") or search_raw.get("bots") or [])],
            )
            networks.append(
                NetworkConfig(
                    name=net_name,
                    server=net_server,
                    channels=net_channels,
                    identity=net_ident,
                    search=net_search,
                )
            )

    if not networks:
        channels = raw.get("channels") or []
        if not channels:
            raise ValueError(
                "config must define `networks` or list at least one channel under `channels`"
            )
        root_server = ServerConfig(
            host=str(server_raw.get("host") or "irc.example.net"),
            port=int(server_raw.get("port") or 6667),
            use_tls=bool(server_raw.get("use_tls") or False),
            password=str(root_password) if root_password else None,
        )
        root_ident = IdentityConfig(
            nick=str(root_nick),
            username=str(identity_raw.get("username") or root_nick),
            realname=str(identity_raw.get("realname") or "Example IRC Client"),
            unique_nick=bool(identity_raw.get("unique_nick", True)),
            x_service=str(identity_raw.get("x_service") or "X@channels.undernet.org"),
            x_username=str(root_x_username) if root_x_username else None,
            x_password=str(root_x_password) if root_x_password else None,
        )
        root_search = SearchConfig(
            command_template=str(search_raw.get("command_template") or "@search {query}"),
            filename_hint=str(search_raw.get("filename_hint") or ""),
            use_query_as_hint=bool(search_raw.get("use_query_as_hint", False)),
            offer_timeout_sec=float(search_raw.get("offer_timeout_sec") or 180),
            search_all_channels=bool(search_raw.get("search_all_channels", False)),
            post_join_delay_sec=float(search_raw.get("post_join_delay_sec") or 8),
            bots=[str(b) for b in (search_raw.get("bots") or [])],
        )
        networks = [
            NetworkConfig(
                name="default",
                server=root_server,
                channels=[str(c) for c in channels],
                identity=root_ident,
                search=root_search,
            )
        ]

    return AppConfig(
        networks=networks,
        dcc=DccConfig(
            auto_accept=bool(dcc_raw.get("auto_accept", True)),
            auto_resume=bool(dcc_raw.get("auto_resume", False)),
            bind_address=str(dcc_raw.get("bind_address") or ""),
            connect_timeout_sec=float(dcc_raw.get("connect_timeout_sec") or 30),
        ),
        staging_dir=staging_path,
        behavior=BehaviorConfig(
            connect_timeout_sec=float(behavior_raw.get("connect_timeout_sec") or 30),
            read_timeout_sec=float(behavior_raw.get("read_timeout_sec") or 60),
            quit_after_download=bool(behavior_raw.get("quit_after_download", True)),
            nick_retry=int(behavior_raw.get("nick_retry") or 5),
            identd=bool(behavior_raw.get("identd", True)),
        ),
    )
