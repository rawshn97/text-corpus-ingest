"""
ArchiveFetcher: IRC @search -> DCC SEND receive -> local staging.

Flow:
  1. Connect to IRC (socket / optional TLS), optional identd
  2. Unique nick, resolve collisions, wait for MOTD
  3. Optional network login (Undernet X LOGIN or NickServ)
  4. JOIN search channel(s) and wait for confirmation
  5. Emit @search on the channel and to configured search bots
  6. Watch PRIVMSG/NOTICE for a matching DCC SEND CTCP
  7. Stream the file into the staging directory
"""

from __future__ import annotations

import argparse
import logging
import random
import re
import sys
import threading
import time
from pathlib import Path

from corpus_ingest.config import (
    AppConfig,
    IdentityConfig,
    NetworkConfig,
    SearchConfig,
    ServerConfig,
    load_config,
)
from corpus_ingest.dcc import DccSendOffer, parse_dcc_send, receive_dcc_send
from corpus_ingest.identd import IdentDaemon
from corpus_ingest.irc_client import IrcClient

logger = logging.getLogger(__name__)

_PRIVMSG_RE = re.compile(
    r"^:(?P<prefix>\S+)\s+(?P<cmd>PRIVMSG|NOTICE)\s+(?P<target>\S+)\s+:(?P<body>.*)$",
    re.IGNORECASE,
)

DEFAULT_SEARCH_TEMPLATE = "@search {query}"
RAW_SEARCH_TEMPLATE = "{query}"
_NICK_MAX = 12


def uniquify_nick(nick: str) -> str:
    """Fit nick + 4-digit suffix into the 12-char Undernet nick limit."""
    suffix = f"{random.randint(0, 9999):04d}"
    base = re.sub(r"[^A-Za-z0-9_\[\]\\`^{}|-]", "", nick) or "lab"
    return f"{base[: _NICK_MAX - len(suffix)]}{suffix}"


def format_search_command(template: str, query: str) -> str:
    """Build the PRIVMSG body from a template and query string."""
    query = query.strip()
    if not query:
        raise ValueError("document query string must be non-empty")
    try:
        return template.format(query=query)
    except (KeyError, ValueError) as exc:
        raise ValueError(f"invalid search.command_template {template!r}: {exc}") from exc


def resolve_filename_hint(
    query: str,
    *,
    filename_hint: str = "",
    use_query_as_hint: bool = False,
) -> str:
    """Return a lowercase filename filter, or '' to accept the first DCC offer."""
    explicit = (filename_hint or "").strip()
    if explicit:
        return explicit.lower()
    if use_query_as_hint:
        return query.strip().lower()
    return ""


def _numeric(line: str) -> str | None:
    parts = line.split()
    if len(parts) >= 2 and parts[1].isdigit():
        return parts[1]
    return None


class ArchiveFetcher:
    """Orchestrates IRC monitoring and inbound DCC transfers for a single network."""

    def __init__(
        self,
        config: AppConfig,
        network: NetworkConfig | None = None,
        ident: IdentDaemon | None = None,
    ) -> None:
        self.config = config
        self.network = network or (config.networks[0] if config.networks else None)
        self.ident = ident

        if self.network is not None:
            self.net_name = self.network.name
            self.server: ServerConfig = self.network.server
            self.identity: IdentityConfig = self.network.identity
            self.channels: list[str] = self.network.channels
            self.search: SearchConfig = self.network.search
        else:
            self.net_name = "default"
            self.server = self.config.server or ServerConfig(host="irc.example.net")
            self.identity = self.config.identity or IdentityConfig(nick="Rawshn")
            self.channels = self.config.channels or ["#bookz"]
            self.search = self.config.search or SearchConfig()

    def fetch(
        self,
        query: str,
        *,
        command_template: str | None = None,
        filename_hint: str | None = None,
        use_query_as_hint: bool | None = None,
        stop_event: threading.Event | None = None,
    ) -> Path:
        search_cmd = format_search_command(
            command_template or self.search.command_template,
            query,
        )
        hint = resolve_filename_hint(
            query.strip(),
            filename_hint=(self.search.filename_hint if filename_hint is None else filename_hint),
            use_query_as_hint=(
                self.search.use_query_as_hint if use_query_as_hint is None else use_query_as_hint
            ),
        )

        nick = self.identity.nick
        if self.identity.unique_nick:
            nick = uniquify_nick(nick)
            logger.info("[%s] Using unique nick %s", self.net_name, nick)

        ident = self.ident
        owns_ident = False
        if ident is None and self.config.behavior.identd:
            ident = IdentDaemon(self.identity.username)
            ident.start()
            owns_ident = True

        try:
            with IrcClient(
                self.server.host,
                self.server.port,
                nick=nick,
                username=self.identity.username,
                realname=self.identity.realname,
                password=self.server.password,
                use_tls=self.server.use_tls,
                connect_timeout=self.config.behavior.connect_timeout_sec,
                read_timeout=self.config.behavior.read_timeout_sec,
            ) as client:
                self._await_registered(client, stop_event=stop_event)
                if stop_event and stop_event.is_set():
                    raise InterruptedError(f"Cancelled on network {self.net_name}")

                self._maybe_x_login(client, stop_event=stop_event)
                if stop_event and stop_event.is_set():
                    raise InterruptedError(f"Cancelled on network {self.net_name}")

                join_channels = self._join_targets()
                for channel in join_channels:
                    self._join_channel(client, channel, stop_event=stop_event)
                    if stop_event and stop_event.is_set():
                        raise InterruptedError(f"Cancelled on network {self.net_name}")

                delay = self.search.post_join_delay_sec
                if delay > 0:
                    logger.info(
                        "[%s] Waiting %.1fs after JOIN before @search",
                        self.net_name,
                        delay,
                    )
                    self._idle(client, delay, stop_event=stop_event)

                if stop_event and stop_event.is_set():
                    raise InterruptedError(f"Cancelled on network {self.net_name}")

                self._emit_search(client, search_cmd)

                offer = self._await_dcc_offer(client, filename_hint=hint, stop_event=stop_event)
                if stop_event and stop_event.is_set():
                    raise InterruptedError(f"Cancelled on network {self.net_name}")

                if offer is None:
                    raise TimeoutError(
                        f"[{self.net_name}] No matching DCC SEND offer within "
                        f"{self.search.offer_timeout_sec}s for query={query!r}."
                    )

                if not self.config.dcc.auto_accept:
                    logger.info(
                        "[%s] DCC offer received for %s but auto_accept=false; skipping transfer",
                        self.net_name,
                        offer.filename,
                    )
                    raise RuntimeError(
                        f"Inbound DCC SEND for {offer.filename!r} ignored (dcc.auto_accept=false)"
                    )

                dest = receive_dcc_send(
                    offer,
                    self.config.staging_dir,
                    connect_timeout=self.config.dcc.connect_timeout_sec,
                )

                if not self.config.behavior.quit_after_download:
                    logger.info(
                        "[%s] Keeping IRC session open (quit_after_download=false)",
                        self.net_name,
                    )
                return dest
        finally:
            if owns_ident and ident is not None:
                ident.close()

    def _join_targets(self) -> list[str]:
        if self.search.search_all_channels:
            return list(self.channels)
        return list(self.channels[:1])

    def _idle(
        self,
        client: IrcClient,
        seconds: float,
        stop_event: threading.Event | None = None,
    ) -> None:
        """Keep reading (and PONGing) instead of a blocking sleep."""
        stop_check = stop_event.is_set if stop_event else None
        client.wait_until(
            lambda _line: False,
            timeout=seconds,
            on_line=self._log_line,
            stop_check=stop_check,
        )

    def _log_line(self, line: str) -> None:
        logger.debug("[%s] << %s", self.net_name, line)

    def _maybe_x_login(self, client: IrcClient, stop_event: threading.Event | None = None) -> None:
        password = self.identity.x_password
        service = self.identity.x_service
        if not password or not service:
            logger.info(
                "[%s] Skipping X LOGIN (no password or service configured)",
                self.net_name,
            )
            return
        user = self.identity.x_username or client.nick
        logger.info("[%s] Sending X LOGIN to %s as %s", self.net_name, service, user)
        client.privmsg(service, f"LOGIN {user} {password}")
        self._idle(client, 4.0, stop_event=stop_event)

    def _emit_search(self, client: IrcClient, search_cmd: str) -> None:
        for target in self._join_targets():
            logger.info("[%s] Sending search on %s: %s", self.net_name, target, search_cmd)
            client.privmsg(target, search_cmd)

        if not search_cmd.startswith("!"):
            for bot in self.search.bots:
                bot = bot.lstrip("+@")
                if not bot:
                    continue
                logger.info("[%s] Sending search to bot %s: %s", self.net_name, bot, search_cmd)
                client.privmsg(bot, search_cmd)
                channel = self._join_targets()[0]
                addressed = f"@{bot} {search_cmd.removeprefix('@search ').strip()}"
                logger.info("[%s] Sending search on %s: %s", self.net_name, channel, addressed)
                client.privmsg(channel, addressed)

    def _await_registered(
        self, client: IrcClient, stop_event: threading.Event | None = None
    ) -> None:
        """Wait for welcome/MOTD; rename on 433 nick-in-use."""
        base_nick = client.nick
        deadline = time.monotonic() + self.config.behavior.connect_timeout_sec
        retries = 0

        def on_line(line: str) -> None:
            nonlocal retries
            logger.debug("[%s] << %s", self.net_name, line)
            code = _numeric(line)
            if code == "433" and retries < self.config.behavior.nick_retry:
                retries += 1
                new_nick = uniquify_nick(base_nick)
                logger.warning("[%s] Nick in use; retrying as %s", self.net_name, new_nick)
                client.set_nick(new_nick)

        def registered(line: str) -> bool:
            code = _numeric(line)
            return code in {"001", "376", "422"}

        remaining = max(deadline - time.monotonic(), 1.0)
        stop_check = stop_event.is_set if stop_event else None
        line = client.wait_until(
            registered,
            timeout=remaining,
            on_line=on_line,
            stop_check=stop_check,
        )
        if line is None:
            if stop_event and stop_event.is_set():
                return
            logger.warning("[%s] Proceeding without confirmed MOTD (timeout)", self.net_name)
        else:
            logger.info("[%s] Registered as %s", self.net_name, client.nick)

    def _join_channel(
        self, client: IrcClient, channel: str, stop_event: threading.Event | None = None
    ) -> None:
        """JOIN and wait for confirmation (self-JOIN or 366 end of NAMES)."""
        if not channel.startswith("#"):
            channel = f"#{channel}"
        client.join(channel)

        nick = client.nick.lower()
        chan = channel.lower()

        def joined(line: str) -> bool:
            upper = line.upper()
            if " JOIN " in upper and (
                f"JOIN :{chan}" in line.lower() or f"JOIN {chan}" in line.lower()
            ):
                prefix = line.split("!", 1)[0].lstrip(":").lower()
                if prefix == nick or nick in prefix:
                    return True
            parts = line.split()
            if len(parts) >= 4 and parts[1] == "366":
                return parts[3].lower().lstrip(":") == chan
            if len(parts) >= 4 and parts[1] in {"471", "473", "474", "475", "477"}:
                logger.error("[%s] JOIN failed for %s: %s", self.net_name, channel, line)
                return True
            return False

        stop_check = stop_event.is_set if stop_event else None
        line = client.wait_until(
            joined,
            timeout=self.config.behavior.connect_timeout_sec,
            on_line=self._log_line,
            stop_check=stop_check,
        )
        if line is None:
            if stop_event and stop_event.is_set():
                return
            logger.warning(
                "[%s] No JOIN confirmation for %s; continuing anyway",
                self.net_name,
                channel,
            )
        else:
            logger.info("[%s] Joined %s", self.net_name, channel)

    def _await_dcc_offer(
        self,
        client: IrcClient,
        *,
        filename_hint: str,
        stop_event: threading.Event | None = None,
    ) -> DccSendOffer | None:
        deadline_timeout = self.search.offer_timeout_sec

        def is_match(line: str) -> bool:
            offer = self._extract_offer(line)
            if offer is None:
                return False
            if filename_hint:
                norm_hint = re.sub(r"[\s_.-]+", " ", filename_hint).strip().lower()
                norm_filename = re.sub(r"[\s_.-]+", " ", offer.filename).strip().lower()
                if (
                    norm_hint not in norm_filename
                    and filename_hint.lower() not in offer.filename.lower()
                ):
                    logger.info(
                        "[%s] Skipping DCC offer %s (hint=%r)",
                        self.net_name,
                        offer.filename,
                        filename_hint,
                    )
                    return False
            return True

        def on_line(line: str) -> None:
            logger.debug("[%s] << %s", self.net_name, line)
            match = _PRIVMSG_RE.match(line)
            if not match:
                return
            body = match.group("body")
            offer = parse_dcc_send(body)
            if offer is not None:
                logger.info(
                    "[%s] Saw DCC SEND candidate: %s (%s bytes) via %s",
                    self.net_name,
                    offer.filename,
                    offer.filesize,
                    match.group("cmd").upper(),
                )
                return
            logger.info("[%s] %s: %s", self.net_name, match.group("cmd").upper(), body)

        stop_check = stop_event.is_set if stop_event else None
        matched_line = client.wait_until(
            is_match,
            timeout=deadline_timeout,
            on_line=on_line,
            stop_check=stop_check,
        )
        if matched_line is None:
            return None
        offer = self._extract_offer(matched_line)
        assert offer is not None
        logger.info(
            "[%s] Accepted DCC SEND: %s from %s:%s (%s bytes)",
            self.net_name,
            offer.filename,
            offer.ip,
            offer.port,
            offer.filesize,
        )
        return offer

    @staticmethod
    def _extract_offer(line: str) -> DccSendOffer | None:
        match = _PRIVMSG_RE.match(line)
        if not match:
            return None
        return parse_dcc_send(match.group("body"))


class MultiNetworkArchiveFetcher:
    """Coordinates search and DCC retrieval across multiple IRC networks concurrently."""

    def __init__(
        self,
        config: AppConfig,
        networks: list[NetworkConfig] | None = None,
    ) -> None:
        self.config = config
        self.networks = networks or config.networks
        if not self.networks:
            raise ValueError("No networks configured for MultiNetworkArchiveFetcher")

    def fetch(
        self,
        query: str,
        *,
        command_template: str | None = None,
        filename_hint: str | None = None,
        use_query_as_hint: bool | None = None,
        stop_on_first: bool | None = None,
    ) -> list[Path]:
        """
        Search across all configured networks concurrently.

        If stop_on_first is True (default when filename_hint or raw template is used),
        the first network to complete DCC transfer signals other networks to stop.
        Returns a list of downloaded file paths.
        """
        if stop_on_first is None:
            stop_on_first = bool(filename_hint or command_template == RAW_SEARCH_TEMPLATE)

        ident: IdentDaemon | None = None
        if self.config.behavior.identd and self.networks:
            ident = IdentDaemon(self.networks[0].identity.username)
            ident.start()

        stop_event = threading.Event()
        results: list[Path] = []
        errors: dict[str, Exception] = {}
        lock = threading.Lock()

        def worker(net: NetworkConfig) -> None:
            fetcher = ArchiveFetcher(self.config, network=net, ident=ident)
            try:
                path = fetcher.fetch(
                    query,
                    command_template=command_template,
                    filename_hint=filename_hint,
                    use_query_as_hint=use_query_as_hint,
                    stop_event=stop_event,
                )
                with lock:
                    results.append(path)
                    if stop_on_first:
                        logger.info(
                            "[%s] Download completed (%s); stopping sibling networks",
                            net.name,
                            path.name,
                        )
                        stop_event.set()
            except InterruptedError:
                logger.info("[%s] Stopped cleanly after sibling completed", net.name)
            except Exception as exc:  # noqa: BLE001
                with lock:
                    errors[net.name] = exc
                logger.warning("[%s] Network search failed: %s", net.name, exc)

        threads = [
            threading.Thread(target=worker, args=(net,), name=f"fetch-{net.name}")
            for net in self.networks
        ]
        try:
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        finally:
            if ident is not None:
                ident.close()

        if not results:
            summary = "; ".join(f"{name}: {err}" for name, err in errors.items())
            raise TimeoutError(f"No DCC transfer completed across networks: {summary}")

        return results


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Lab IRC multi-network @search + DCC fetch into staging/",
    )
    parser.add_argument(
        "--query",
        "-q",
        required=True,
        help="Search terms (wrapped with @search by default)",
    )
    parser.add_argument(
        "--network",
        "-n",
        default="all",
        help="Target network by name, or 'all' to search all configured networks (default: all)",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to irc.yaml (default: config/irc.yaml)",
    )
    parser.add_argument(
        "--template",
        default=None,
        help='PRIVMSG template with {query} (default: from config, "@search {query}")',
    )
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Send --query verbatim (equivalent to --template '{query}')",
    )
    parser.add_argument(
        "--hint",
        default=None,
        help="Require this substring in the DCC filename (overrides config)",
    )
    parser.add_argument(
        "--stop-on-first",
        action="store_true",
        help="Stop all networks as soon as any network completes a download",
    )
    parser.add_argument(
        "--all-results",
        action="store_true",
        help="Keep all networks running to collect search results from all networks",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Debug logging",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.raw and args.template:
        logger.error("Use either --raw or --template, not both")
        return 2

    config = load_config(args.config)
    config.staging_dir.mkdir(parents=True, exist_ok=True)

    template = RAW_SEARCH_TEMPLATE if args.raw else args.template

    target_networks = config.networks
    if args.network and args.network.lower() != "all":
        target_networks = [n for n in config.networks if n.name.lower() == args.network.lower()]
        if not target_networks:
            available = ", ".join(n.name for n in config.networks)
            logger.error("Network %r not found. Configured networks: %s", args.network, available)
            return 2

    stop_on_first: bool | None = None
    if args.stop_on_first:
        stop_on_first = True
    elif args.all_results:
        stop_on_first = False

    fetcher = MultiNetworkArchiveFetcher(config, networks=target_networks)
    try:
        paths = fetcher.fetch(
            args.query,
            command_template=template,
            filename_hint=args.hint,
            stop_on_first=stop_on_first,
        )
    except (TimeoutError, OSError, ValueError) as exc:
        logger.error("%s", exc)
        return 1

    for p in paths:
        print(p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
