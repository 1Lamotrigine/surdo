"""Маршруты комнат для преподавателя (монтируются под `/rooms/`)."""

from django.urls import path

from rooms import views

app_name = "rooms"

urlpatterns = [
    path("new/", views.create_room_view, name="create"),
    path("<str:join_code>/", views.room_detail, name="detail"),
]
