from __future__ import annotations

import json
import struct
import zlib
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import brotli

PROTO_COMMAND = 0
PROTO_HEARTBEAT = 1
PROTO_ZLIB = 2
PROTO_BROTLI = 3

TYPE_HEARTBEAT = 2
TYPE_HEARTBEAT_REPLY = 3
TYPE_COMMAND = 5
TYPE_AUTH = 7
TYPE_AUTH_REPLY = 8


@dataclass(frozen=True, slots=True)
class PacketHeader:
    total_size: int
    header_size: int
    proto: int
    packet_type: int
    sequence: int


def make_packet(proto: int, packet_type: int, body: bytes, sequence: int = 1) -> bytes:
    return struct.pack(">IHHII", 16 + len(body), 16, proto, packet_type, sequence) + body


def auth_packet(room_id: int, token: str, uid: int = 0) -> bytes:
    body = json.dumps(
        {"uid": uid, "roomid": room_id, "protover": 3, "platform": "web", "type": 2, "key": token},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return make_packet(PROTO_HEARTBEAT, TYPE_AUTH, body)


def heartbeat_packet() -> bytes:
    return make_packet(PROTO_HEARTBEAT, TYPE_HEARTBEAT, b"[object Object]", 1)


def _packet_at(data: bytes, offset: int) -> tuple[PacketHeader, bytes, int] | None:
    if len(data) - offset < 16:
        return None
    total, header_size, proto, packet_type, sequence = struct.unpack_from(">IHHII", data, offset)
    if header_size < 16 or total < header_size or offset + total > len(data):
        return None
    header = PacketHeader(total, header_size, proto, packet_type, sequence)
    return header, data[offset + header_size : offset + total], offset + total


def _decompress(proto: int, body: bytes, max_size: int) -> bytes:
    if proto == PROTO_COMMAND or proto == PROTO_HEARTBEAT:
        return body
    if proto == PROTO_ZLIB:
        result = zlib.decompress(body)
    elif proto == PROTO_BROTLI:
        result = brotli.decompress(body)
    else:
        return b""
    if len(result) > max_size:
        raise ValueError("decompressed websocket payload is too large")
    return result


def _iter_documents(data: bytes, max_size: int, depth: int = 0) -> Iterator[dict[str, Any]]:
    if depth > 4:
        return
    offset = 0
    while True:
        parsed = _packet_at(data, offset)
        if parsed is None:
            return
        header, body, offset = parsed
        if header.packet_type not in {TYPE_COMMAND, TYPE_AUTH_REPLY}:
            if offset >= len(data):
                return
            continue
        if body.lstrip().startswith((b"{", b"[")):
            try:
                document = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                continue
            if isinstance(document, dict):
                yield document
            elif isinstance(document, list):
                for item in document:
                    if isinstance(item, dict):
                        yield item
            continue
        try:
            expanded = _decompress(header.proto, body, max_size)
        except (ValueError, zlib.error, brotli.error):
            continue
        if expanded:
            yield from _iter_documents(expanded, max_size, depth + 1)


def iter_documents(data: bytes, max_size: int = 8 * 1024 * 1024) -> Iterator[dict[str, Any]]:
    yield from _iter_documents(data, max_size)
