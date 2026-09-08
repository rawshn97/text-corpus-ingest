"""Minimal blocking IRC client over TCP (optional TLS)."""

from __future__ import annotations

import logging
import socket
import ssl
import time
from collections.abc import Callable, Iterator
from typing import Self

logger = logging.getLogger(__name__)

LineHandler = Callable[[str], None]


def _redact_irc_line(line: str) -> str:
    """Avoid logging CService / PASS secrets."""
    upper = line.upper()
    if upper.startswith("PASS ") or " LOGIN " in f" {upper}":
        return "<redacted auth command>"
    return line


class IrcClient:
    """Thin socket IRC session: register, join, PRIVMSG, and line iteration."""

    def __init__(
        self,
        host: str,
        port: int,
        *,
        nick: str,
        username: str,
        realname: str,
        password: str | None = None,
        use_tls: bool = False,
        connect_timeout: float = 30.0,
        read_timeout: float = 60.0,
    ) -> None:
        self.host = host
        self.port = port
        self.nick = nick
        self.username = username
        self.realname = realname
        self.password = password
        self.use_tls = use_tls
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout

        self._sock: socket.socket | ssl.SSLSocket | None = None
        self._buffer = ""

    def connect(self) -> None:
        raw = socket.create_connection((self.host, self.port), timeout=self.connect_timeout)
        if self.use_tls:
            ctx = ssl.create_default_context()
            self._sock = ctx.wrap_socket(raw, server_hostname=self.host)
        else:
            self._sock = raw
        self._sock.settimeout(self.read_timeout)
        logger.info("Connected to %s:%s (tls=%s)", self.host, self.port, self.use_tls)

        if self.password:
            self.send_raw(f"PASS {self.password}")
        self.send_raw(f"NICK {self.nick}")
        self.send_raw(f"USER {self.username} 0 * :{self.realname}")

    def close(self) -> None:
        if self._sock is not None:
            try:
                self.send_raw("QUIT :corpus ingest done")
            except OSError:
                pass
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def __enter__(self) -> Self:
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def send_raw(self, line: str) -> None:
        if self._sock is None:
            raise RuntimeError("IRC socket is not connected")
        payload = (line.rstrip("\r\n") + "\r\n").encode("utf-8", errors="replace")
        self._sock.sendall(payload)
        logger.debug(">> %s", _redact_irc_line(line))

    def set_nick(self, nick: str) -> None:
        self.nick = nick
        self.send_raw(f"NICK {nick}")

    def join(self, channel: str) -> None:
        if not channel.startswith("#"):
            channel = f"#{channel}"
        self.send_raw(f"JOIN {channel}")

    def privmsg(self, target: str, text: str) -> None:
        self.send_raw(f"PRIVMSG {target} :{text}")

    def lines(
        self,
        *,
        until: float | None = None,
        stop_check: Callable[[], bool] | None = None,
    ) -> Iterator[str]:
        """
        Yield CRLF-delimited IRC lines; auto-replies to PING.

        If ``until`` (monotonic deadline) is set, socket read timeouts before
        that deadline are ignored so long waits (e.g. DCC offer) keep going.
        """
        while True:
            if until is not None and time.monotonic() >= until:
                return
            if stop_check is not None and stop_check():
                return
            line = self._readline(until=until, stop_check=stop_check)
            if line is None:
                return
            if line.upper().startswith("PING "):
                self.send_raw("PONG " + line[5:])
                continue
            yield line

    def wait_until(
        self,
        predicate: Callable[[str], bool],
        *,
        timeout: float,
        on_line: LineHandler | None = None,
        stop_check: Callable[[], bool] | None = None,
    ) -> str | None:
        deadline = time.monotonic() + timeout
        for line in self.lines(until=deadline, stop_check=stop_check):
            if on_line:
                on_line(line)
            if predicate(line):
                return line
            if stop_check is not None and stop_check():
                return None
            if time.monotonic() >= deadline:
                return None
        return None

    def _readline(
        self,
        *,
        until: float | None = None,
        stop_check: Callable[[], bool] | None = None,
    ) -> str | None:
        if self._sock is None:
            return None
        while "\n" not in self._buffer:
            if until is not None:
                remaining = until - time.monotonic()
                if remaining <= 0:
                    return None
                recv_timeout = min(self.read_timeout, max(remaining, 0.05))
            else:
                recv_timeout = self.read_timeout
            if stop_check is not None:
                recv_timeout = min(recv_timeout, 1.5)
            self._sock.settimeout(recv_timeout)
            try:
                chunk = self._sock.recv(4096)
            except TimeoutError:
                if stop_check is not None and stop_check():
                    return None
                if until is not None and time.monotonic() < until:
                    continue
                return None
            if not chunk:
                return None
            self._buffer += chunk.decode("utf-8", errors="replace")

        line, self._buffer = self._buffer.split("\n", 1)
        return line.rstrip("\r")
