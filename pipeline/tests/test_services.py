"""Сервис E1: сохранение фразы и упрощённые глоссы."""

from datetime import timedelta

import pytest
from django.utils import timezone

from dictionary.models import Language, Sign, SignStatus, UnknownWord, UnknownWordStatus
from pipeline.models import Utterance
from pipeline.services import (
    UtteranceValidationError,
    create_utterance,
    lag_level,
    recent_room_utterances,
    record_display_started,
    sign_language_for_room,
    verified_sign_glosses,
)
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


@pytest.fixture
def signs(owner):
    for gloss in ("ОТКРЫТЬ", "УЧЕБНИК", "СТРАНИЦА"):
        Sign.objects.create(gloss=gloss, lang=Language.RSL, status=SignStatus.VERIFIED)
    return Sign.objects.all()


def test_create_utterance_saves_text_glosses_and_metrics(room, signs):
    started_at = timezone.now()

    utterance = create_utterance(
        room,
        "Учебник   страница, Иванов",
        asr_ms=420,
        started_at=started_at,
    )

    assert utterance.seq == 1
    assert utterance.text == "Учебник страница, Иванов"
    assert utterance.asr_ms == 420
    assert utterance.gloss_ms is not None
    assert utterance.display_lag_ms is None
    assert utterance.degraded is False
    assert utterance.started_at == started_at
    glow = utterance.glosses
    assert glow["lang"] == Language.RSL
    assert glow["sentence_type"] == "statement"
    assert [token["type"] for token in glow["tokens"]] == [
        "sign",
        "sign",
        "fingerspell",
    ]
    assert glow["tokens"][0]["gloss"] == "УЧЕБНИК"
    assert glow["tokens"][1]["gloss"] == "СТРАНИЦА"
    assert glow["tokens"][2]["letters"] == ["И", "В", "А", "Н", "О", "В"]
    assert glow["unknown"] == ["Иванов"]


def test_seq_increments_per_room(room, owner, signs):
    other_room = Room.objects.create(owner=owner)

    first = create_utterance(room, "Учебник")
    second = create_utterance(room, "Страница")
    other = create_utterance(other_room, "Учебник")

    assert (first.seq, second.seq, other.seq) == (1, 2, 1)


def test_unknown_word_goes_to_queue_and_counts_each_occurrence(room, signs):
    create_utterance(room, "Иванов")
    create_utterance(room, "Иванов и снова Иванов")

    word = UnknownWord.objects.get(lemma="Иванов", lang=Language.RSL)
    assert word.count == 3
    assert word.status == UnknownWordStatus.NEW


def test_glosses_report_unknown_without_duplicates(room, signs):
    utterance = create_utterance(room, "Иванов Иванов")

    assert utterance.glosses["unknown"] == ["Иванов"]
    assert UnknownWord.objects.get(lemma="Иванов").count == 2


def test_only_verified_signs_are_used(room):
    Sign.objects.create(gloss="УЧЕБНИК", lang=Language.RSL, status=SignStatus.DRAFT)

    utterance = create_utterance(room, "Учебник")

    assert utterance.glosses["tokens"][0]["type"] == "fingerspell"
    assert utterance.glosses["unknown"] == ["Учебник"]
    assert verified_sign_glosses(Language.RSL) == {}


def test_room_language_selects_dictionary_language(owner):
    kk_room = Room.objects.create(owner=owner, lang=Room.Language.KK)
    Sign.objects.create(gloss="УЧЕБНИК", lang=Language.KSL, status=SignStatus.VERIFIED)

    utterance = create_utterance(kk_room, "Учебник Кітап")

    assert sign_language_for_room(kk_room) == Language.KSL
    assert utterance.glosses["lang"] == Language.KSL
    assert utterance.glosses["tokens"][0]["gloss"] == "УЧЕБНИК"
    # Очередь слов различает языки жестов.
    word = UnknownWord.objects.get(lemma="Кітап")
    assert word.lang == Language.KSL
    assert not UnknownWord.objects.filter(lang=Language.RSL).exists()


def test_explicit_lang_overrides_room_language(room):
    Sign.objects.create(gloss="УЧЕБНИК", lang=Language.KSL, status=SignStatus.VERIFIED)

    utterance = create_utterance(room, "Учебник", lang=Language.KSL)

    assert utterance.glosses["lang"] == Language.KSL
    assert utterance.glosses["tokens"][0]["gloss"] == "УЧЕБНИК"


def test_empty_text_is_rejected(room):
    with pytest.raises(UtteranceValidationError):
        create_utterance(room, "   \n ")

    assert Utterance.objects.count() == 0


def test_too_long_text_is_rejected(room):
    with pytest.raises(UtteranceValidationError):
        create_utterance(room, "а" * 2001)

    assert Utterance.objects.count() == 0


def test_unknown_language_is_rejected(room):
    with pytest.raises(UtteranceValidationError):
        create_utterance(room, "Учебник", lang="de")


def test_empty_phrase_does_not_touch_unknown_queue(room):
    with pytest.raises(UtteranceValidationError):
        create_utterance(room, "")

    assert UnknownWord.objects.count() == 0


@pytest.mark.parametrize(
    ("lag_ms", "expected"),
    [
        (0, "green"),
        (5_000, "green"),
        (5_001, "yellow"),
        (10_000, "yellow"),
        (10_001, "red"),
    ],
)
def test_lag_level_thresholds(lag_ms, expected):
    """FR-15: зелёный ≤5 с, жёлтый ≤10 с, красный выше 10 с."""
    assert lag_level(lag_ms) == expected


def test_display_started_persists_lag_and_sends_level(room):
    started_at = timezone.now() - timedelta(seconds=6)
    utterance = create_utterance(room, "Учебник", started_at=started_at)

    status = record_display_started(
        room.pk,
        utterance.pk,
        received_at=started_at + timedelta(seconds=6),
    )

    utterance.refresh_from_db()
    assert utterance.display_lag_ms == 6_000
    assert status is not None
    assert status.lag_ms == 6_000
    assert status.level == "yellow"
    assert utterance.as_event()["display_lag_ms"] == 6_000


def test_display_started_is_idempotent(room):
    started_at = timezone.now() - timedelta(seconds=2)
    utterance = create_utterance(room, "Учебник", started_at=started_at)

    record_display_started(
        room.pk,
        utterance.pk,
        received_at=started_at + timedelta(seconds=2),
    )
    status = record_display_started(
        room.pk,
        utterance.pk,
        received_at=started_at + timedelta(seconds=20),
    )

    utterance.refresh_from_db()
    assert utterance.display_lag_ms == 2_000
    assert status is not None
    assert status.level == "green"


def test_display_started_from_foreign_room_is_ignored(room, owner):
    other_room = Room.objects.create(owner=owner)
    utterance = create_utterance(other_room, "Учебник")

    assert record_display_started(room.pk, utterance.pk) is None
    utterance.refresh_from_db()
    assert utterance.display_lag_ms is None


def test_recent_room_utterances_returns_last_phrases_in_order(room, owner):
    other_room = Room.objects.create(owner=owner)
    for index in range(3):
        create_utterance(room, f"Фраза {index}")
    create_utterance(other_room, "Чужая фраза")

    phrases = recent_room_utterances(room, limit=2)

    assert [utterance.seq for utterance in phrases] == [2, 3]
    assert [utterance.text for utterance in phrases] == ["Фраза 1", "Фраза 2"]
