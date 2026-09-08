"""Tiny RFC 1413 ident responder (optional; bind of port 113 often needs root)."""

from __future__ import annotations

import logging
import socket
import threading
from types import TracebackType
from typing import Self

logger = logging.getLogger(__name__)


class IdentDaemon:
    """Answer ident queries so IRC servers do not log 'No ident response'."""

    def __init__(self, username: str, port: int = 113) -> None:
        self.username = username
        self.port = port
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> bool:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("0.0.0.0", self.port))
            sock.listen(5)
            sock.settimeout(0.5)
        except OSError as exc:
            logger.warning("identd not started on port %s: %s", self.port, exc)
            return False

        self._sock = sock
        self._thread = threading.Thread(target=self._serve, name="identd", daemon=True)
        self._thread.start()
        logger.info("identd listening on %s (userid=%s)", self.port, self.username)
        return True

    def close(self) -> None:
        self._stop.set()
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def _serve(self) -> None:
        assert self._sock is not None
        while not self._stop.is_set():
            try:
                conn, _addr = self._sock.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            try:
                conn.settimeout(3.0)
                query = conn.recv(64).decode("ascii", errors="replace").strip()
                if query:
                    reply = f"{query} : USERID : UNIX : {self.username}\r\n"
                    conn.sendall(reply.encode("ascii", errors="replace"))
            except OSError:
                pass
            finally:
                try:
                    conn.close()
                except OSError:
                    pass
