"""Unit tests for DCC SEND parsing (no network)."""

from __future__ import annotations

import struct

from corpus_ingest.dcc import parse_dcc_send


def test_parse_dcc_send_basic() -> None:
    ip_int = struct.unpack("!I", bytes((127, 0, 0, 1)))[0]
    body = f"\x01DCC SEND gutenberg-84.txt {ip_int} 5000 12345\x01"
    offer = parse_dcc_send(body)
    assert offer is not None
    assert offer.filename == "gutenberg-84.txt"
    assert offer.ip == "127.0.0.1"
    assert offer.port == 5000
    assert offer.filesize == 12345


def test_parse_dcc_send_quoted_filename() -> None:
    ip_int = struct.unpack("!I", bytes((10, 0, 0, 2)))[0]
    body = f'\x01DCC SEND "Frankenstein PD.txt" {ip_int} 9999 100\x01'
    offer = parse_dcc_send(body)
    assert offer is not None
    assert offer.filename == "Frankenstein PD.txt"
    assert offer.ip == "10.0.0.2"


def test_parse_rejects_path_traversal() -> None:
    ip_int = 1
    body = f"\x01DCC SEND ../../etc/passwd {ip_int} 1 1\x01"
    offer = parse_dcc_send(body)
    assert offer is not None
    assert offer.filename == "passwd"


def test_parse_none_when_absent() -> None:
    assert parse_dcc_send("hello channel") is None


def test_parse_dcc_send_without_trailing_ctcp() -> None:
    ip_int = struct.unpack("!I", bytes((127, 0, 0, 1)))[0]
    body = f"\x01DCC SEND results.txt {ip_int} 5000 10"
    offer = parse_dcc_send(body)
    assert offer is not None
    assert offer.filename == "results.txt"
    assert offer.port == 5000
