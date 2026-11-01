from pathlib import Path

from bili_live_danmaku.models import ChatMessage, Fragment, MessageKind, TTSSettings
from bili_live_danmaku.tts import TTSService, message_to_speech


def message(message_id: str, text: str, kind: MessageKind = MessageKind.TEXT) -> ChatMessage:
    return ChatMessage(
        id=message_id,
        kind=kind,
        user="VincentZyu",
        parts=[Fragment(type="text", text=text)],
    )


def test_message_to_speech_includes_username_and_limits_length() -> None:
    text = message_to_speech(message("1", "你好世界"), include_username=True, max_chars=8)
    assert text == "VincentZ"
    assert message_to_speech(message("2", "测试"), include_username=False, max_chars=20) == "测试"


async def test_tts_disabled_does_not_enqueue(tmp_path: Path) -> None:
    service = TTSService(TTSSettings(enabled=False), tmp_path)
    await service.enqueue(message("1", "不会朗读"))
    assert service.queue.empty()


async def test_tts_filters_message_kinds(tmp_path: Path) -> None:
    settings = TTSSettings(enabled=True, read_kinds=[MessageKind.TEXT])
    service = TTSService(settings, tmp_path)
    await service.enqueue(message("1", "普通弹幕", MessageKind.TEXT))
    await service.enqueue(message("2", "礼物", MessageKind.GIFT))
    assert service.queue.qsize() == 1
    assert await service.queue.get() == "VincentZyu说：普通弹幕"


async def test_tts_queue_drops_oldest_when_full(tmp_path: Path) -> None:
    settings = TTSSettings(enabled=True, queue_size=1)
    service = TTSService(settings, tmp_path)
    await service.enqueue(message("1", "第一条"))
    await service.enqueue(message("2", "第二条"))
    assert service.queue.qsize() == 1
    assert await service.queue.get() == "VincentZyu说：第二条"


def test_event_specific_speech_templates() -> None:
    assert message_to_speech(message("1", "投喂 小心心", MessageKind.GIFT), True, 100) == (
        "VincentZyu投喂 小心心"
    )
    assert message_to_speech(message("2", "进入了直播间", MessageKind.ENTRY), True, 100) == (
        "VincentZyu进入了直播间"
    )
    assert message_to_speech(message("3", "为主播点赞了", MessageKind.LIKE), True, 100) == (
        "VincentZyu为主播点赞了"
    )
    paid = ChatMessage(
        id="4",
        kind=MessageKind.PAID,
        user="VincentZyu",
        parts=[Fragment(type="text", text="晚上好")],
        amount="CN¥30",
    )
    assert message_to_speech(paid, True, 100) == "VincentZyu发送了一条醒目留言：晚上好，金额 30 元"
