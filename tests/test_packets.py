from __future__ import annotations

import json
import zlib

import brotli

from bili_live_danmaku.bili.packets import (
    PROTO_BROTLI,
    PROTO_COMMAND,
    PROTO_ZLIB,
    TYPE_COMMAND,
    auth_packet,
    iter_documents,
    make_packet,
)


def test_plain_json_packet() -> None:
    body = json.dumps({"cmd": "DANMU_MSG"}).encode()
    documents = list(iter_documents(make_packet(PROTO_COMMAND, TYPE_COMMAND, body)))
    assert documents == [{"cmd": "DANMU_MSG"}]


def test_nested_brotli_packets() -> None:
    inner = make_packet(
        PROTO_COMMAND,
        TYPE_COMMAND,
        json.dumps({"cmd": "LIKE_INFO_V3_CLICK"}).encode(),
    )
    outer = make_packet(PROTO_BROTLI, TYPE_COMMAND, brotli.compress(inner))
    assert [item["cmd"] for item in iter_documents(outer)] == ["LIKE_INFO_V3_CLICK"]


def test_nested_zlib_packets() -> None:
    inner = make_packet(
        PROTO_COMMAND,
        TYPE_COMMAND,
        json.dumps({"cmd": "INTERACT_WORD_V2"}).encode(),
    )
    outer = make_packet(PROTO_ZLIB, TYPE_COMMAND, zlib.compress(inner))
    assert [item["cmd"] for item in iter_documents(outer)] == ["INTERACT_WORD_V2"]


def test_auth_packet_contains_json_uid_and_room() -> None:
    packet = auth_packet(21452505, "token-value", 12345)
    assert packet[6:8] == b"\x00\x01"
    body = json.loads(packet[16:])
    assert body == {
        "uid": 12345,
        "roomid": 21452505,
        "protover": 3,
        "platform": "web",
        "type": 2,
        "key": "token-value",
    }
