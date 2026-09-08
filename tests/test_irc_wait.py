"""Tests for IrcClient wait_until deadline behavior (no network)."""

from __future__ import annotations

import socket
import threading
import time

from corpus_ingest.irc_client import IrcClient


def _serve_slow_lines(ready: threading.Event, port_box: list[int]) -> None:
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port_box.append(srv.getsockname()[1])
    ready.set()
    conn, _ = srv.accept()
    # Client will NICK/USER; ignore and later send one line after a gap.
    conn.settimeout(1.0)
    try:
        conn.recv(1024)
    except TimeoutError:
        pass
    time.sleep(1.2)
    conn.sendall(b":lab.local 001 test :Welcome\r\n")
    time.sleep(0.2)
    conn.close()
    srv.close()


def test_wait_until_survives_socket_read_timeout() -> None:
    """Offer waits must continue past read_timeout until the outer deadline."""
    ready = threading.Event()
    ports: list[int] = []
    threading.Thread(target=_serve_slow_lines, args=(ready, ports), daemon=True).start()
    assert ready.wait(2)

    client = IrcClient(
        "127.0.0.1",
        ports[0],
        nick="test",
        username="test",
        realname="test",
        connect_timeout=2,
        read_timeout=0.3,  # shorter than the server's silence gap
    )
    client.connect()
    try:
        line = client.wait_until(
            lambda line_str: "001" in line_str,
            timeout=3.0,
        )
        assert line is not None
        assert "001" in line
    finally:
        client.close()
