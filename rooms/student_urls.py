"""Маршруты входа студента (монтируются в корень: `/r/<code>/`).

Ссылка внутри QR-кода всегда ведёт на корень сайта, поэтому маршруты не
попадают под префикс приложения `rooms/`.
"""

from django.urls import path

from rooms import views

app_name = "room_student"

urlpatterns = [
    path("r/<str:join_code>/", views.room_join, name="join"),
    path("r/<str:join_code>/live/", views.room_student, name="live"),
]
