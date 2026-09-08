"""Parse and receive IRC DCC SEND file transfers."""

from __future__ import annotations

import logging
import re
import socket
import struct
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# CTCP: \x01DCC SEND <filename> <ip> <port> [<filesize>] [<token>]\x01
# Filename may be quoted when it contains spaces. Trailing CTCP byte is optional
# (some daemons strip it).
_DCC_SEND_RE = re.compile(
    r"\x01DCC SEND "
    r"(?P<filename>\"[^\"]+\"|\S+)\s+"
    r"(?P<ip>\d+)\s+"
    r"(?P<port>\d+)"
    r"(?: (?P<size>\d+))?"
    r"(?: (?P<token>\d+))?"
    r"\x01?",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DccSendOffer:
    filename: str
    ip: str
    port: int
    filesize: int | None
    raw: str


def parse_dcc_send(message: str) -> DccSendOffer | None:
    """Extract a DCC SEND offer from a PRIVMSG / NOTICE body."""
    match = _DCC_SEND_RE.search(message)
    if not match:
        return None

    filename = match.group("filename")
    if filename.startswith('"') and filename.endswith('"'):
        filename = filename[1:-1]

    # Sanitize path components: never allow directory traversal from offers.
    filename = Path(filename).name
    if not filename:
        return None

    ip_int = int(match.group("ip"))
    ip = socket.inet_ntoa(struct.pack("!I", ip_int & 0xFFFFFFFF))
    port = int(match.group("port"))
    size_raw = match.group("size")
    filesize = int(size_raw) if size_raw is not None else None

    return DccSendOffer(
        filename=filename,
        ip=ip,
        port=port,
        filesize=filesize,
        raw=match.group(0),
    )


def receive_dcc_send(
    offer: DccSendOffer,
    dest_dir: Path,
    *,
    connect_timeout: float = 30.0,
    chunk_size: int = 65536,
) -> Path:
    """
    Connect to the peer and stream the DCC SEND payload into dest_dir.

    Implements classic DCC SEND acknowledgement: after each chunk, send a
    4-byte big-endian total-bytes-received counter (mod 2**32).
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / offer.filename
    if dest_path.exists():
        dest_path = _unique_path(dest_path)

    logger.info(
        "DCC connecting to %s:%s for %s (%s bytes)",
        offer.ip,
        offer.port,
        offer.filename,
        offer.filesize if offer.filesize is not None else "unknown",
    )

    with socket.create_connection((offer.ip, offer.port), timeout=connect_timeout) as sock:
        sock.settimeout(60.0)
        received = 0
        with dest_path.open("wb") as out:
            while True:
                if offer.filesize is not None and received >= offer.filesize:
                    break
                try:
                    chunk = sock.recv(chunk_size)
                except TimeoutError:
                    if offer.filesize is None:
                        break
                    raise
                if not chunk:
                    break
                out.write(chunk)
                received += len(chunk)
                # Classic DCC ACK (unsigned 32-bit received count).
                sock.sendall(struct.pack("!I", received & 0xFFFFFFFF))
                if offer.filesize is not None and received >= offer.filesize:
                    break

    if offer.filesize is not None and received != offer.filesize:
        raise IOError(
            f"DCC incomplete for {offer.filename}: got {received} of {offer.filesize} bytes"
        )

    logger.info("DCC saved %s (%s bytes)", dest_path, received)
    return dest_path


def _unique_path(path: Path) -> Path:
    stem, suffix = path.stem, path.suffix
    for i in range(1, 1000):
        candidate = path.with_name(f"{stem}_{i}{suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"Too many existing copies of {path.name}")
