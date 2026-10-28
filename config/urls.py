from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from config import pwa, views
from dictionary.api import create_sign_api, dictionary_api, review_sign_api
from dictionary.views import clip_file
from pipeline.api import phrase_api, text_api
from rooms.api import chat_history_api, create_room_api

urlpatterns = [
    path("", views.home, name="home"),
    path("health/", views.health, name="health"),
    path("partials/htmx-demo/", views.htmx_demo, name="htmx-demo"),
    path("avatar/", views.avatar_test, name="avatar-test"),
    # PWA отдаётся с корня сайта: только так service worker получает область
    # видимости `/` и управляет страницами комнаты (G1, FR-23/FR-24).
    path(pwa.MANIFEST_FILENAME, pwa.manifest, name="pwa-manifest"),
    path(pwa.SW_FILENAME, pwa.service_worker, name="pwa-service-worker"),
    path("accounts/", include("accounts.urls")),
    path("rooms/", include("rooms.urls")),
    path("dictionary/", include("dictionary.urls")),
    path("", include("rooms.student_urls")),
    path("api/rooms/", create_room_api, name="api-room-create"),
    path("api/rooms/<str:join_code>/history/", chat_history_api, name="api-room-history"),
    path("api/rooms/<str:join_code>/text/", text_api, name="api-room-text"),
    path("api/rooms/<str:join_code>/phrase/", phrase_api, name="api-room-phrase"),
    path("api/dictionary/", dictionary_api, name="api-dictionary"),
    path("api/signs/", create_sign_api, name="api-sign-create"),
    path("api/signs/<int:sign_id>/review/", review_sign_api, name="api-sign-review"),
    # Совпадает с публичным URL клипа (в проде перехватывает Caddy).
    path("media/clips/<int:clip_id>.json.gz", clip_file, name="clip-file"),
    # Анимационные клипы (H1): VRMA/glTF с расширением файла.
    path(
        "media/clips/<int:clip_id>.<str:ext>",
        clip_file,
        name="clip-file-animation",
    ),
    path("admin/", admin.site.urls),
]

# В разработке Django сам раздаёт медиа (модель аватара, клипы). В проде это
# делает Caddy из тома `/srv/media`; правило активно только при DEBUG=True.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
