"""Управление комнатой: закрытие, смена ID и удаление участника."""

from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.urls import reverse

from rooms import management, presence
from rooms.models import Participant, Room

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def room(owner):
    return Room.objects.create(owner=owner, join_code="MANAGE")


def test_rotate_join_code_changes_code(room):
    old_code = room.join_code

    new_code = management.rotate_join_code(room)

    room.refresh_from_db()
    assert new_code != old_code
    assert room.join_code == new_code
    assert len(new_code) == 6


def test_rotate_join_code_retries_on_collision(room, owner):
    Room.objects.create(owner=owner, join_code="TAKEN1")

    with patch(
        "rooms.management.generate_join_code",
        side_effect=("TAKEN1", "FREE22"),
    ):
        new_code = management.rotate_join_code(room)

    assert new_code == "FREE22"


def test_old_code_stops_resolving_after_rotate(room, client):
    old_code = room.join_code
    new_code = management.rotate_join_code(room)

    assert (
        client.get(reverse("room_student:join", kwargs={"join_code": old_code})).status_code
        == 404
    )
    assert (
        client.get(reverse("room_student:join", kwargs={"join_code": new_code})).status_code
        == 200
    )


def test_close_room_clears_presence(room):
    presence.add_connection(room.pk, key="session:abc", name="Гость")

    management.close_room(room)

    room.refresh_from_db()
    assert room.is_closed
    assert presence.list_participants(room.pk) == []


def test_close_room_is_idempotent(room):
    management.close_room(room)
    closed_at = room.closed_at

    management.close_room(room)
    room.refresh_from_db()

    assert room.closed_at == closed_at


def test_remove_participant_marks_removed(room):
    participant = Participant.objects.create(room=room, guest_name="Гость", session_key="s1")

    management.remove_participant(participant)

    participant.refresh_from_db()
    assert not participant.is_active


def test_remove_participant_clears_presence(room):
    participant = Participant.objects.create(room=room, guest_name="Гость", session_key="s1")
    presence.add_connection(
        room.pk, key="session:s1", name="Гость", participant_id=participant.pk
    )

    management.remove_participant(participant)

    assert presence.list_participants(room.pk) == []


# --- HTTP-действия преподавателя ---


def test_close_view_requires_login(client, room):
    response = client.post(reverse("rooms:close", kwargs={"join_code": room.join_code}))

    assert response.status_code == 302
    assert reverse("accounts:login") in response.url


def test_close_view_rejects_other_teacher(client, room, other_teacher):
    client.force_login(other_teacher)

    response = client.post(reverse("rooms:close", kwargs={"join_code": room.join_code}))

    assert response.status_code == 403


def test_close_view_closes_room(client, owner, room):
    client.force_login(owner)

    response = client.post(reverse("rooms:close", kwargs={"join_code": room.join_code}))

    room.refresh_from_db()
    assert response.status_code == 302
    assert room.is_closed


def test_close_view_rejects_get(client, owner, room):
    client.force_login(owner)

    response = client.get(reverse("rooms:close", kwargs={"join_code": room.join_code}))

    assert response.status_code == 405


def test_rotate_view_changes_code_and_redirects(client, owner, room):
    client.force_login(owner)
    old_code = room.join_code

    response = client.post(reverse("rooms:rotate-code", kwargs={"join_code": old_code}))

    room.refresh_from_db()
    assert response.status_code == 302
    assert room.join_code != old_code
    assert room.join_code in response.url


def test_rotate_view_rejects_other_teacher(client, room, other_teacher):
    client.force_login(other_teacher)

    response = client.post(reverse("rooms:rotate-code", kwargs={"join_code": room.join_code}))

    assert response.status_code == 403


def test_rotate_view_on_closed_room_keeps_code(client, owner, room):
    room.close()
    client.force_login(owner)
    old_code = room.join_code

    response = client.post(reverse("rooms:rotate-code", kwargs={"join_code": old_code}))

    room.refresh_from_db()
    assert response.status_code == 302
    assert room.join_code == old_code


def test_remove_participant_view(client, owner, room):
    client.force_login(owner)
    participant = Participant.objects.create(room=room, guest_name="Гость", session_key="s1")

    response = client.post(
        reverse(
            "rooms:remove-participant",
            kwargs={"join_code": room.join_code, "participant_id": participant.pk},
        )
    )

    participant.refresh_from_db()
    assert response.status_code == 302
    assert not participant.is_active


def test_remove_participant_view_rejects_other_teacher(client, room, other_teacher):
    client.force_login(other_teacher)
    participant = Participant.objects.create(room=room, guest_name="Гость", session_key="s1")

    response = client.post(
        reverse(
            "rooms:remove-participant",
            kwargs={"join_code": room.join_code, "participant_id": participant.pk},
        )
    )

    participant.refresh_from_db()
    assert response.status_code == 403
    assert participant.is_active


def test_remove_participant_view_refuses_owner(client, owner, room):
    client.force_login(owner)
    participant = Participant.objects.create(room=room, user=owner)

    response = client.post(
        reverse(
            "rooms:remove-participant",
            kwargs={"join_code": room.join_code, "participant_id": participant.pk},
        )
    )

    participant.refresh_from_db()
    assert response.status_code == 302
    assert participant.is_active


def test_remove_participant_view_unknown_id_is_404(client, owner, room):
    client.force_login(owner)

    response = client.post(
        reverse(
            "rooms:remove-participant",
            kwargs={"join_code": room.join_code, "participant_id": 999999},
        )
    )

    assert response.status_code == 404


def test_removed_guest_is_redirected_from_live(client, owner, room):
    from rooms.services import GUEST_ROOMS_SESSION_KEY

    participant = Participant.objects.create(room=room, guest_name="Гость", session_key="s1")
    session = client.session
    session[GUEST_ROOMS_SESSION_KEY] = {room.join_code: {"name": "Гость", "room_id": room.pk}}
    session.save()
    management.remove_participant(participant)

    response = client.get(reverse("room_student:live", kwargs={"join_code": room.join_code}))

    assert response.status_code == 302
    assert response.url == reverse("room_student:join", kwargs={"join_code": room.join_code})


def test_admin_rotate_codes_action(admin_user, room):
    from django.contrib.admin.sites import AdminSite
    from django.contrib.messages.middleware import MessageMiddleware
    from django.contrib.messages.storage.fallback import FallbackStorage
    from django.contrib.sessions.middleware import SessionMiddleware
    from django.test import RequestFactory

    from rooms.admin import RoomAdmin

    model_admin = RoomAdmin(Room, AdminSite())
    old_code = room.join_code

    request = RequestFactory().post("/admin/")
    SessionMiddleware(lambda r: None).process_request(request)
    request.session.save()
    MessageMiddleware(lambda r: None).process_request(request)
    request._messages = FallbackStorage(request)

    model_admin.rotate_codes(request, Room.objects.filter(pk=room.pk))

    room.refresh_from_db()
    assert room.join_code != old_code
