from pathlib import Path

from bili_live_danmaku.models import ChatMessage, Fragment, MessageKind, TTSSettings
from bili_live_danmaku.tts import (
    SpeechRequest,
    TTSService,
    detect_language,
    message_to_speech,
    message_to_speech_segments,
)


def message(
    message_id: str,
    text: str,
    kind: MessageKind = MessageKind.TEXT,
    *,
    user: str = "VincentZyu",
) -> ChatMessage:
    return ChatMessage(
        id=message_id,
        kind=kind,
        user=user,
        parts=[Fragment(type="text", text=text)],
    )


def test_language_detection_uses_scripts_and_priority() -> None:
    priority = ["zh", "en", "ja", "ko", "es", "fr", "de", "pt", "ru", "it"]
    assert detect_language("你好世界", priority) == "zh"
    assert detect_language("かなちゃん", priority) == "ja"
    assert detect_language("김철수", priority) == "ko"
    assert detect_language("Светлана", priority) == "ru"
    assert detect_language("VincentZyu", priority, short_text=True) == "en"
    assert detect_language("123 !!!", priority) == "zh"


def test_message_to_speech_includes_username_and_limits_length() -> None:
    text = message_to_speech(message("1", "你好世界"), include_username=True, max_chars=9)
    assert text == "VincentZy"
    assert message_to_speech(message("2", "测试"), include_username=False, max_chars=20) == "测试"


def test_japanese_username_uses_japanese_voice_and_chinese_body_stays_chinese() -> None:
    settings = TTSSettings(enabled=True)
    segments = message_to_speech_segments(message("1", "你好", user="かなちゃん"), settings)
    assert [(segment.text, segment.language) for segment in segments] == [
        ("かなちゃん", "ja"),
        ("说：你好", "zh"),
    ]
    assert segments[0].voice == "ja-JP-NanamiNeural"
    assert segments[1].voice == "zh-CN-XiaoxiaoNeural"


def test_same_voice_segments_are_merged() -> None:
    settings = TTSSettings(enabled=True)
    segments = message_to_speech_segments(message("1", "你好", user="小明"), settings)
    assert len(segments) == 1
    assert segments[0].text == "小明说：你好"
    assert segments[0].language == "zh"


def test_mixed_body_is_split_by_sentence_and_voice() -> None:
    settings = TTSSettings(enabled=True)
    segments = message_to_speech_segments(message("1", "你好。Hello!", user="小明"), settings)
    assert [(segment.text, segment.language) for segment in segments] == [
        ("小明说：你好。", "zh"),
        ("Hello!", "en"),
    ]


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
    request = await service.queue.get()
    assert isinstance(request, SpeechRequest)
    assert "".join(segment.text for segment in request.segments) == "VincentZyu说：普通弹幕"


async def test_tts_queue_drops_oldest_whole_message_when_full(tmp_path: Path) -> None:
    settings = TTSSettings(enabled=True, queue_size=1)
    service = TTSService(settings, tmp_path)
    await service.enqueue(message("1", "第一条"))
    await service.enqueue(message("2", "第二条"))
    assert service.queue.qsize() == 1
    request = await service.queue.get()
    assert request.message_id == "2"
    assert "".join(segment.text for segment in request.segments) == "VincentZyu说：第二条"


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
