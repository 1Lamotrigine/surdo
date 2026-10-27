"""Очередь нераспознанных слов: агрегация повторов, статусы, интерфейс."""

import pytest
from django.urls import reverse

from accounts.models import Role
from dictionary.models import Language, UnknownWord, UnknownWordStatus
from dictionary.services import (
    UnknownWordValidationError,
    list_unknown_words,
    mark_unknown_word_recorded,
    queue_unknown_word,
    record_unknown_word,
    record_unknown_words,
    unknown_word_payload,
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


@pytest.fixture
def teacher(django_user_model):
    return django_user_model.objects.create_user(
        email="teacher@example.com",
        password="StrongPass-12345",
        name="Преподаватель",
        role=Role.TEACHER,
    )


# --- Агрегация повторов (критерий B7) --------------------------------------


def test_first_occurrence_creates_word_with_count_one():
    word = record_unknown_word("Иванов")

    assert word.count == 1
    assert word.status == UnknownWordStatus.NEW
    assert UnknownWord.objects.count() == 1


def test_repeated_occurrence_increments_count():
    record_unknown_word("Иванов")
    record_unknown_word("Иванов")
    word = record_unknown_word("Иванов")

    assert word.count == 3
    assert UnknownWord.objects.count() == 1  # одна запись, не три


def test_repeat_updates_last_seen_at():
    first = record_unknown_word("Иванов")
    first.last_seen_at = first.last_seen_at.replace(year=2020)
    first.save(update_fields=("last_seen_at",))
    old = first.last_seen_at

    word = record_unknown_word("Иванов")

    assert word.last_seen_at > old


def test_same_lemma_in_other_language_is_separate():
    record_unknown_word("Иванов", lang=Language.RSL)
    record_unknown_word("Иванов", lang=Language.KSL)

    assert UnknownWord.objects.count() == 2


def test_lemma_is_normalized():
    record_unknown_word("  Иван   Иванов  ")
    word = record_unknown_word("Иван Иванов")

    assert word.count == 2
    assert word.lemma == "Иван Иванов"


def test_empty_lemma_is_rejected():
    with pytest.raises(UnknownWordValidationError):
        record_unknown_word("   ")

    assert UnknownWord.objects.count() == 0


def test_unknown_language_is_rejected():
    with pytest.raises(UnknownWordValidationError):
        record_unknown_word("Иванов", lang="xx")


def test_record_many_aggregates():
    record_unknown_words(["Иванов", "Иванов", "Петров"])

    assert UnknownWord.objects.count() == 2
    assert UnknownWord.objects.get(lemma="Иванов").count == 2
    assert UnknownWord.objects.get(lemma="Петров").count == 1


def test_recorded_word_keeps_status_but_counts():
    word = record_unknown_word("Иванов")
    queue_unknown_word(word)
    mark_unknown_word_recorded(word)

    again = record_unknown_word("Иванов")

    assert again.count == 2
    assert again.status == UnknownWordStatus.RECORDED


# --- Список для редактора --------------------------------------------------


def test_list_orders_by_count_desc():
    record_unknown_word("редкое")
    record_unknown_word("частое")
    record_unknown_word("частое")
    record_unknown_word("среднее")
    record_unknown_word("среднее")
    record_unknown_word("среднее")

    words = list_unknown_words()

    assert [w.lemma for w in words] == ["среднее", "частое", "редкое"]


def test_list_excludes_recorded_by_default():
    word = record_unknown_word("Иванов")
    queue_unknown_word(word)
    mark_unknown_word_recorded(word)
    record_unknown_word("Петров")

    words = list_unknown_words()

    assert [w.lemma for w in words] == ["Петров"]


def test_list_can_include_recorded():
    word = record_unknown_word("Иванов")
    queue_unknown_word(word)
    mark_unknown_word_recorded(word)

    words = list_unknown_words(include_recorded=True)

    assert [w.lemma for w in words] == ["Иванов"]


def test_list_filters_by_language():
    record_unknown_word("Иванов", lang=Language.RSL)
    record_unknown_word("Кітап", lang=Language.KSL)

    words = list_unknown_words(lang=Language.KSL)

    assert [w.lemma for w in words] == ["Кітап"]


def test_list_filters_by_status():
    plain = record_unknown_word("Иванов")
    queued = record_unknown_word("Петров")
    queue_unknown_word(queued)

    words = list_unknown_words(status=UnknownWordStatus.QUEUED)

    assert [w.lemma for w in words] == ["Петров"]
    assert plain.status == UnknownWordStatus.NEW


def test_unknown_word_payload_shape():
    word = record_unknown_word("Иванов")

    payload = unknown_word_payload(word)

    assert payload["lemma"] == "Иванов"
    assert payload["count"] == 1
    assert payload["status"] == UnknownWordStatus.NEW
    assert payload["lang"] == Language.RSL
    assert "last_seen_at" in payload


# --- Переходы статусов -----------------------------------------------------


def test_queue_word_from_new():
    word = record_unknown_word("Иванов")

    queue_unknown_word(word)

    word.refresh_from_db()
    assert word.status == UnknownWordStatus.QUEUED


def test_mark_recorded_from_queued():
    word = record_unknown_word("Иванов")
    queue_unknown_word(word)

    mark_unknown_word_recorded(word)

    word.refresh_from_db()
    assert word.status == UnknownWordStatus.RECORDED


def test_cannot_record_directly_from_new():
    word = record_unknown_word("Иванов")

    with pytest.raises(UnknownWordValidationError):
        mark_unknown_word_recorded(word)

    word.refresh_from_db()
    assert word.status == UnknownWordStatus.NEW


def test_unknown_status_is_rejected():
    from dictionary.services import transition_unknown_word

    word = record_unknown_word("Иванов")

    with pytest.raises(UnknownWordValidationError):
        transition_unknown_word(word, to_status="nonsense")


# --- Интерфейс редактора ---------------------------------------------------


def test_queue_page_requires_login(client):
    response = client.get(reverse("dictionary:unknown-queue"))

    assert response.status_code == 302
    assert reverse("accounts:login") in response.url


def test_queue_page_rejects_teacher(client, teacher):
    client.force_login(teacher)

    response = client.get(reverse("dictionary:unknown-queue"))

    assert response.status_code == 403


def test_queue_page_lists_words_with_count(client, editor):
    record_unknown_word("Иванов")
    record_unknown_word("Иванов")
    record_unknown_word("Петров")
    client.force_login(editor)

    response = client.get(reverse("dictionary:unknown-queue"))

    assert response.status_code == 200
    body = response.content.decode()
    assert "Иванов" in body
    assert "Петров" in body
    # Самое частое слово идёт раньше редкого.
    assert body.index("Иванов") < body.index("Петров")


def test_queue_page_empty_message(client, editor):
    client.force_login(editor)

    response = client.get(reverse("dictionary:unknown-queue"))

    assert response.status_code == 200
    assert "Очередь пуста" in response.content.decode()


def test_queue_page_filters_by_language(client, editor):
    record_unknown_word("Иванов", lang=Language.RSL)
    record_unknown_word("Кітап", lang=Language.KSL)
    client.force_login(editor)

    response = client.get(reverse("dictionary:unknown-queue"), {"lang": Language.KSL})

    body = response.content.decode()
    assert "Кітап" in body
    assert "Иванов" not in body


def test_queue_page_links_queued_word_to_recording(client, editor):
    word = record_unknown_word("Иванов")
    queue_unknown_word(word)
    client.force_login(editor)

    response = client.get(reverse("dictionary:unknown-queue"))
    html = response.content.decode()

    assert f"{reverse('dictionary:record')}?word={word.pk}" in html
    assert "Записать жест" in html


def test_queue_action_takes_word_in_work(client, editor):
    word = record_unknown_word("Иванов")
    client.force_login(editor)

    response = client.post(
        reverse("dictionary:unknown-word-action", kwargs={"word_id": word.pk}),
        {"action": "queue"},
    )

    assert response.status_code == 302
    word.refresh_from_db()
    assert word.status == UnknownWordStatus.QUEUED


def test_queue_action_marks_recorded(client, editor):
    word = record_unknown_word("Иванов")
    queue_unknown_word(word)
    client.force_login(editor)

    client.post(
        reverse("dictionary:unknown-word-action", kwargs={"word_id": word.pk}),
        {"action": "recorded"},
    )

    word.refresh_from_db()
    assert word.status == UnknownWordStatus.RECORDED


def test_queue_action_rejects_forbidden_transition(client, editor):
    word = record_unknown_word("Иванов")  # new
    client.force_login(editor)

    client.post(
        reverse("dictionary:unknown-word-action", kwargs={"word_id": word.pk}),
        {"action": "recorded"},
    )

    word.refresh_from_db()
    assert word.status == UnknownWordStatus.NEW


def test_expert_can_open_queue(client, expert):
    record_unknown_word("Иванов")
    client.force_login(expert)

    response = client.get(reverse("dictionary:unknown-queue"))

    assert response.status_code == 200
