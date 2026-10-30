from __future__ import annotations

import asyncio
import base64
import json

from bili_live_danmaku.bili.events import EventParser, EventProcessor, dwell_for
from bili_live_danmaku.bili.protobuf import ProtoMessage
from bili_live_danmaku.models import ChatMessage, MessageKind


def _varint(value: int) -> bytes:
    result = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            result.append(byte | 0x80)
        else:
            result.append(byte)
            return bytes(result)


def _field(number: int, value: int | bytes) -> bytes:
    key = _varint((number << 3) | (0 if isinstance(value, int) else 2))
    if isinstance(value, int):
        return key + _varint(value)
    return key + _varint(len(value)) + value


def _pb(*fields: bytes) -> str:
    return base64.b64encode(b"".join(fields)).decode()


def _danmu_info(text: str, user: str, dm_type: int = 0) -> list[object]:
    head: list[object] = [0, 0, 0, 0, 1_700_000_000_000, 0, 0, 0, 0, 0, 0, 0, dm_type]
    head.append({"url": "https://i0.hdslb.com/emote.png", "height": 20})
    head.append(None)
    head.append(
        {
            "extra": json.dumps(
                {"emots": {"[汤圆]": {"url": "https://i0.hdslb.com/tangyuan.png", "height": 20}}}
            ),
            "user": {
                "base": {
                    "name": user,
                    "face": "https://i1.hdslb.com/avatar.jpg",
                    "name_color": 0x79D7FF,
                },
                "guard": {"guard_level": 3},
            },
        }
    )
    return [head, text, [0, "fallback"]]


def test_parse_danmu_with_inline_emote_and_avatar() -> None:
    message = EventParser().parse({"cmd": "DANMU_MSG", "info": _danmu_info("[汤圆] 你好", "观众A")})
    assert message is not None
    assert message.kind == MessageKind.TEXT
    assert message.user == "观众A"
    assert message.avatar_url == "https://i1.hdslb.com/avatar.jpg"
    assert message.user_color == "#79d7ff"
    assert [part.type for part in message.parts] == ["emote", "text"]


def test_parse_interact_word_protobuf() -> None:
    pb = _pb(_field(2, "进入者".encode()), _field(8, 1_700_000_000_000))
    message = EventParser().parse({"cmd": "INTERACT_WORD_V2", "data": {"pb": pb}})
    assert message is not None
    assert message.kind == MessageKind.ENTRY
    assert message.user == "进入者"
    assert message.timestamp_ms == 1_700_000_000_000


def test_parse_gift_protobuf() -> None:
    icon = _pb(_field(1, b"https://i0.hdslb.com/gift.png"))
    gift = _pb(
        _field(1, 100),
        _field(2, "小心心".encode()),
        _field(3, 6),
        _field(10, 1_700_000_000),
        _field(18, "投喂".encode()),
        _field(35, base64.b64decode(icon)),
    )
    root = _pb(
        _field(2, "送礼人".encode()),
        _field(3, b"https://i1.hdslb.com/gift-face.jpg"),
        _field(10, base64.b64decode(gift)),
    )
    message = EventParser().parse({"cmd": "SEND_GIFT_V2", "data": {"pb": root}})
    assert message is not None
    assert message.kind == MessageKind.GIFT
    assert message.count == 6
    assert message.parts[0].verb is True
    assert message.parts[1].url == "https://i0.hdslb.com/gift.png"


def test_parse_super_chat_and_membership() -> None:
    parser = EventParser()
    paid = parser.parse(
        {
            "cmd": "SUPER_CHAT_MESSAGE",
            "data": {
                "user_info": {"uname": "SC用户", "face": "//i1.hdslb.com/a.jpg", "guard_level": 3},
                "start_time": 100,
                "price": 30,
                "message": "醒目留言",
            },
        }
    )
    assert paid is not None
    assert paid.kind == MessageKind.PAID
    assert paid.amount == "CN¥30"
    assert paid.dwell_ms == 60_000

    membership = parser.parse(
        {
            "cmd": "GUARD_BUY",
            "data": {"username": "舰长", "start_time": 100, "price": 138000, "guard_level": 3},
        }
    )
    assert membership is not None
    assert membership.amount == "舰长 · CN¥138"


def test_protobuf_nested_field_parser() -> None:
    nested = _pb(_field(2, b"name"))
    root = ProtoMessage(_field(10, base64.b64decode(nested)))
    assert root.get_sub(10).get_str(2) == "name"


def test_dwell_bands() -> None:
    assert dwell_for(49) == 60_000
    assert dwell_for(50) == 120_000
    assert dwell_for(2000) == 7_200_000


async def test_entry_and_gift_merging() -> None:
    emitted: list[ChatMessage] = []

    async def emit(message: ChatMessage) -> None:
        emitted.append(message)

    processor = EventProcessor(emit, entry_merge_seconds=0.02, gift_merge_seconds=0.02)
    await processor.submit(
        ChatMessage(
            id="entry-1",
            kind=MessageKind.ENTRY,
            user="A",
            parts=[{"type": "text", "text": "进入了直播间"}],
        )
    )
    await processor.submit(
        ChatMessage(
            id="entry-2",
            kind=MessageKind.ENTRY,
            user="B",
            parts=[{"type": "text", "text": "进入了直播间"}],
        )
    )
    gift = ChatMessage(
        id="gift-1",
        kind=MessageKind.GIFT,
        user="G",
        merge_key="gift/1/heart",
        count=2,
    )
    await processor.submit(gift)
    await processor.submit(gift.model_copy(update={"id": "gift-2", "count": 3}))
    await asyncio.sleep(0.04)
    await processor.shutdown()
    assert [message.user for message in emitted] == ["A", "G"]
    assert emitted[0].count == 2
    assert emitted[1].count == 5
