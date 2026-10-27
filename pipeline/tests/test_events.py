"""События E3: ссылки на клипы и рассылка в группу комнаты."""

import asyncio
import threading
from types import SimpleNamespace

import pytest
from django.utils import timezone

from dictionary.models import Language, Sign, SignClip, SignStatus
from pipeline import events
from pipeline.events import clip_refs_for_glosses, utterance_event
from pipeline.services import create_utterance
from rooms.models import Room

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner(django_user_model):
    return django_user_model.objects.create_user(
        email="teacher@example.com",
        password="StrongPass-12345",
        name="Преподаватель",
    )


@pytest.fixture
def room(owner):
    return Room.objects.create(owner=owner, lang=Room.Language.RU)


def make_sign(gloss: str, *, status: str = SignStatus.VERIFIED) -> Sign:
    return Sign.objects.create(gloss=gloss, lang=Language.RSL, status=status)


def make_clip(sign: Sign, *, version: int = 1, frames: int = 30):
    return SignClip.objects.create(
        sign=sign,
        file=f"clips/{sign.pk}-{version}.json.gz",
        fps=30,
        frames=frames,
        duration_ms=round(frames / 30 * 1000),
        version=version,
    )


def test_clip_refs_follow_show_order_and_best_clip(room):
    textbook = make_sign("УЧЕБНИК")
    old_clip = make_clip(textbook, version=1, frames=90)
    best_clip = make_clip(textbook, version=2, frames=15)
    letter = make_sign("ДАКТИЛЬ_И")
    letter_clip = make_clip(letter)
    number = make_sign("ЦИФРА_7")
    number_clip = make_clip(number)
    # Черновик с клипом не должен попасть в показ студенту.
    draft = make_sign("ДАКТИЛЬ_В", status=SignStatus.DRAFT)
    make_clip(draft)

    utterance = create_utterance(room, "Учебник Иванов 7")
    refs = clip_refs_for_glosses(utterance.glosses)

    assert [ref["token_index"] for ref in refs] == [0, 1, 2]
    assert [ref["kind"] for ref in refs] == ["sign", "fingerspell", "number"]
    assert [ref["gloss"] for ref in refs] == ["УЧЕБНИК", "ДАКТИЛЬ_И", "ЦИФРА_7"]
    assert refs[0]["url"] == best_clip.file_url()
    assert refs[0]["url"] != old_clip.file_url()
    assert refs[1]["url"] == letter_clip.file_url()
    assert refs[2]["url"] == number_clip.file_url()


def test_utterance_event_contains_glosses_and_clips(room):
    textbook = make_sign("УЧЕБНИК")
    clip = make_clip(textbook)
    utterance = create_utterance(room, "Учебник", started_at=timezone.now())

    event = utterance_event(utterance)

    assert event["id"] == utterance.pk
    assert event["seq"] == 1
    assert event["glosses"] == utterance.glosses
    assert len(event["clips"]) == 1
    assert event["clips"][0]["url"] == clip.file_url()


def test_utterance_event_has_empty_clips_when_dictionary_is_empty(room):
    utterance = create_utterance(room, "Неизвестноеслово")

    assert utterance_event(utterance)["clips"] == []


class FakeChannelLayer:
    def __init__(self) -> None:
        self.sent: list[tuple[str, dict]] = []

    async def group_send(self, group: str, event: dict) -> None:
        self.sent.append((group, event))


def run_with_loop(callback):
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    try:
        events.bind_event_loop(loop)
        callback()
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=5)


def test_broadcast_asr_text_sends_to_room_group(monkeypatch):
    layer = FakeChannelLayer()
    monkeypatch.setattr(events, "get_channel_layer", lambda: layer)

    run_with_loop(lambda: events.broadcast_asr_text(42, "Учебник"))

    assert layer.sent == [
        ("room_42", {"type": "asr.text", "text": "Учебник"}),
    ]


def test_broadcast_utterance_sends_payload(monkeypatch):
    layer = FakeChannelLayer()
    monkeypatch.setattr(events, "get_channel_layer", lambda: layer)
    utterance = SimpleNamespace(
        room_id=7,
        as_event=lambda: {"id": 1, "seq": 1, "text": "Учебник"},
        glosses={},
    )

    run_with_loop(lambda: events.broadcast_utterance(utterance))

    group, payload = layer.sent[0]
    assert group == "room_7"
    assert payload["type"] == "utterance"
    assert payload["utterance"]["text"] == "Учебник"
    assert payload["utterance"]["clips"] == []


def test_broadcast_utterance_sends_unknown_words(monkeypatch):
    layer = FakeChannelLayer()
    monkeypatch.setattr(events, "get_channel_layer", lambda: layer)
    utterance = SimpleNamespace(
        pk=9,
        room_id=7,
        as_event=lambda: {"id": 9, "seq": 1, "text": "Иванов"},
        glosses={"unknown": ["Иванов", "Петров"]},
    )

    run_with_loop(lambda: events.broadcast_utterance(utterance))

    assert layer.sent[1] == (
        "room_7",
        {
            "type": "unknown.words",
            "words": ["Иванов", "Петров"],
            "utterance_id": 9,
        },
    )
