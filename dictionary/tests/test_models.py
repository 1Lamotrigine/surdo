"""Модели словаря: значения по умолчанию, ограничения и версии."""

import pytest
from django.db import IntegrityError, transaction

from accounts.models import Role
from dictionary.models import (
    DictionaryVersion,
    Language,
    Sign,
    SignClip,
    SignStatus,
    UnknownWord,
    UnknownWordStatus,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def editor(django_user_model):
    return django_user_model.objects.create_user(
        email="editor@example.com",
        password="StrongPass-12345",
        name="Редактор",
        role=Role.EDITOR,
    )


@pytest.fixture
def expert(django_user_model):
    return django_user_model.objects.create_user(
        email="expert@example.com",
        password="StrongPass-12345",
        name="Эксперт",
        role=Role.EXPERT,
    )


def test_sign_defaults(editor):
    sign = Sign.objects.create(gloss="УЧЕБНИК", recorded_by=editor)

    assert sign.lang == Language.RSL
    assert sign.status == SignStatus.DRAFT
    assert sign.description == ""
    assert sign.comment == ""
    assert sign.verified_by is None
    assert sign.verified_at is None
    assert not sign.is_verified
    assert sign.recorded_by == editor


def test_verified_sign_gloss_lang_is_unique(expert):
    Sign.objects.create(gloss="УЧЕБНИК", lang=Language.RSL, status=SignStatus.VERIFIED)

    with pytest.raises(IntegrityError), transaction.atomic():
        Sign.objects.create(
            gloss="УЧЕБНИК", lang=Language.RSL, status=SignStatus.VERIFIED
        )


def test_draft_duplicates_are_allowed(expert):
    Sign.objects.create(gloss="УЧЕБНИК", lang=Language.RSL, status=SignStatus.DRAFT)

    duplicate = Sign.objects.create(
        gloss="УЧЕБНИК", lang=Language.RSL, status=SignStatus.DRAFT
    )

    assert duplicate.pk is not None


def test_same_gloss_in_other_language_is_allowed(expert):
    Sign.objects.create(gloss="УЧЕБНИК", lang=Language.RSL, status=SignStatus.VERIFIED)

    other = Sign.objects.create(
        gloss="УЧЕБНИК", lang=Language.KSL, status=SignStatus.VERIFIED
    )

    assert other.pk is not None


def test_verify_fills_expert_and_timestamp(expert):
    sign = Sign.objects.create(gloss="ПРИВЕТ")

    sign.verify(expert, comment="Хорошо читается")

    sign.refresh_from_db()
    assert sign.status == SignStatus.VERIFIED
    assert sign.verified_by == expert
    assert sign.verified_at is not None
    assert sign.comment == "Хорошо читается"
    assert sign.is_verified


def test_verify_keeps_existing_comment_when_empty(expert):
    sign = Sign.objects.create(gloss="ПРИВЕТ", comment="Черновой комментарий")

    sign.verify(expert)

    sign.refresh_from_db()
    assert sign.comment == "Черновой комментарий"


def test_best_clip_prefers_latest_version(editor):
    sign = Sign.objects.create(gloss="УЧЕБНИК", recorded_by=editor)
    SignClip.objects.create(sign=sign, file="clips/v1.json.gz", version=1, frames=40)
    latest = SignClip.objects.create(
        sign=sign, file="clips/v2.json.gz", version=2, frames=30
    )

    assert sign.best_clip == latest


def test_best_clip_prefers_more_frames_within_version(editor):
    sign = Sign.objects.create(gloss="УЧЕБНИК", recorded_by=editor)
    SignClip.objects.create(sign=sign, file="clips/a.json.gz", version=1, frames=20)
    better = SignClip.objects.create(
        sign=sign, file="clips/b.json.gz", version=1, frames=50
    )

    assert sign.best_clip == better


def test_best_clip_is_none_without_clips(editor):
    sign = Sign.objects.create(gloss="УЧЕБНИК", recorded_by=editor)

    assert sign.best_clip is None


def test_sign_clip_defaults(editor):
    sign = Sign.objects.create(gloss="УЧЕБНИК", recorded_by=editor)
    clip = SignClip.objects.create(sign=sign, file="clips/a.json.gz")

    assert clip.fps == 30
    assert clip.duration_ms == 0
    assert clip.frames == 0
    assert clip.version == 1
    assert clip.size_bytes == 0
    assert clip.created_at is not None


def test_unknown_word_defaults():
    word = UnknownWord.objects.create(lemma="Иванов")

    assert word.lang == Language.RSL
    assert word.count == 1
    assert word.status == UnknownWordStatus.NEW
    assert word.last_seen_at is not None


def test_unknown_word_lemma_lang_is_unique():
    UnknownWord.objects.create(lemma="Иванов", lang=Language.RSL)

    with pytest.raises(IntegrityError), transaction.atomic():
        UnknownWord.objects.create(lemma="Иванов", lang=Language.RSL)


def test_unknown_words_ordered_by_count_desc():
    UnknownWord.objects.create(lemma="редкое", lang=Language.RSL, count=1)
    top = UnknownWord.objects.create(lemma="частое", lang=Language.RSL, count=9)
    middle = UnknownWord.objects.create(lemma="среднее", lang=Language.RSL, count=5)

    assert list(UnknownWord.objects.all()) == [top, middle, UnknownWord.objects.get(lemma="редкое")]


def test_dictionary_version_lang_number_is_unique():
    DictionaryVersion.objects.create(lang=Language.RSL, number=1)

    with pytest.raises(IntegrityError), transaction.atomic():
        DictionaryVersion.objects.create(lang=Language.RSL, number=1)


def test_dictionary_version_next_number_starts_at_one():
    assert DictionaryVersion.next_number(Language.RSL) == 1


def test_dictionary_version_bump_increments_per_language():
    first = DictionaryVersion.bump(Language.RSL)
    second = DictionaryVersion.bump(Language.RSL)
    other = DictionaryVersion.bump(Language.KSL)

    assert first.number == 1
    assert second.number == 2
    assert other.number == 1


def test_dictionary_version_current_is_latest():
    DictionaryVersion.objects.create(lang=Language.RSL, number=1)
    latest = DictionaryVersion.objects.create(lang=Language.RSL, number=2)
    DictionaryVersion.objects.create(lang=Language.KSL, number=5)

    assert DictionaryVersion.current(Language.RSL) == latest
    assert DictionaryVersion.current(Language.KSL).number == 5


def test_dictionary_version_current_is_none_without_versions():
    assert DictionaryVersion.current(Language.RSL) is None
