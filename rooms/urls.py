"""Маршруты комнат для преподавателя (монтируются под `/rooms/`)."""

from django.urls import path

from rooms import views

app_name = "rooms"

urlpatterns = [
    path("new/", views.create_room_view, name="create"),
    path("<str:join_code>/", views.room_detail, name="detail"),
    path("<str:join_code>/live/", views.room_live, name="live"),
    path("<str:join_code>/close/", views.room_close, name="close"),
    path("<str:join_code>/rotate-code/", views.room_rotate_code, name="rotate-code"),
    path(
        "<str:join_code>/participants/<int:participant_id>/remove/",
        views.room_remove_participant,
        name="remove-participant",
    ),
]
