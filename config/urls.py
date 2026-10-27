from django.contrib import admin
from django.urls import include, path

from config import views
from rooms.api import chat_history_api, create_room_api

urlpatterns = [
    path("", views.home, name="home"),
    path("health/", views.health, name="health"),
    path("partials/htmx-demo/", views.htmx_demo, name="htmx-demo"),
    path("accounts/", include("accounts.urls")),
    path("rooms/", include("rooms.urls")),
    path("", include("rooms.student_urls")),
    path("api/rooms/", create_room_api, name="api-room-create"),
    path("api/rooms/<str:join_code>/history/", chat_history_api, name="api-room-history"),
    path("admin/", admin.site.urls),
]
