from django.contrib import admin
from django.urls import include, path

from config import views
from dictionary.api import create_sign_api, dictionary_api, review_sign_api
from dictionary.views import clip_file
from rooms.api import chat_history_api, create_room_api

urlpatterns = [
    path("", views.home, name="home"),
    path("health/", views.health, name="health"),
    path("partials/htmx-demo/", views.htmx_demo, name="htmx-demo"),
    path("avatar/", views.avatar_test, name="avatar-test"),
    path("accounts/", include("accounts.urls")),
    path("rooms/", include("rooms.urls")),
    path("dictionary/", include("dictionary.urls")),
    path("", include("rooms.student_urls")),
    path("api/rooms/", create_room_api, name="api-room-create"),
    path("api/rooms/<str:join_code>/history/", chat_history_api, name="api-room-history"),
    path("api/dictionary/", dictionary_api, name="api-dictionary"),
    path("api/signs/", create_sign_api, name="api-sign-create"),
    path("api/signs/<int:sign_id>/review/", review_sign_api, name="api-sign-review"),
    # Совпадает с публичным URL клипа (в проде перехватывает Caddy).
    path("media/clips/<int:clip_id>.json.gz", clip_file, name="clip-file"),
    path("admin/", admin.site.urls),
]
