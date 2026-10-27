"""JSON/multipart API конвейера фраз: текст (E2) и аудио (F6)."""

from __future__ import annotations

import json
import logging

from django.http import HttpRequest, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_POST

from pipeline.queue import submit_audio, submit_text
from pipeline.services import UtteranceValidationError, normalize_text
from rooms.models import Room
from rooms.services import find_open_room

logger = logging.getLogger(__name__)

# 8 секунд WAV 16 кГц mono 16 бит занимают ~256 КБ; 2 МиБ оставляют запас
# для Opus-контейнеров и защищают память процесса от случайных больших файлов.
MAX_PHRASE_AUDIO_BYTES = 2 * 1024 * 1024

_ALLOWED_AUDIO_TYPES = {
    "application/ogg",
    "application/octet-stream",
    "video/webm",
}
_ALLOWED_AUDIO_SUFFIXES = {
    ".wav",
    ".wave",
    ".ogg",
    ".opus",
    ".webm",
    ".mp3",
    ".m4a",
    ".flac",
}


def _can_send_text(user, room: Room) -> bool:
    """Отправлять фразы может только владелец комнаты или администратор."""
    return bool(
        user.is_authenticated
        and (getattr(user, "is_admin", False) or room.owner_id == user.pk)
    )


def _read_payload(request: HttpRequest):
    if request.content_type == "application/json":
        try:
            payload = json.loads(request.body or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None, JsonResponse({"detail": "Некорректный JSON."}, status=400)
        if not isinstance(payload, dict):
            return None, JsonResponse({"detail": "Ожидался JSON-объект."}, status=400)
        return payload, None
    return request.POST, None


@require_POST
def text_api(request: HttpRequest, join_code: str) -> JsonResponse:
    """Принять текст фразы и обработать его в фоне (ТЗ 7.4, этап E2).

    Доступ только у преподавателя этой комнаты (или администратора): гость и
    посторонний преподаватель получают 403, аноним — 401. Ответ 202 означает,
    что фраза встала в очередь: глоссы и сохранение ``Utterance`` идут в
    фоновом обработчике и не блокируют WebSocket-чат комнаты.
    """
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Требуется вход."}, status=401)

    room = find_open_room(join_code)
    if room is None:
        return JsonResponse({"detail": "Комната не найдена или закрыта."}, status=404)
    if not _can_send_text(request.user, room):
        return JsonResponse(
            {"detail": "Отправлять фразы может только преподаватель этой комнаты."},
            status=403,
        )

    payload, error = _read_payload(request)
    if error is not None:
        return error

    try:
        text = normalize_text(payload.get("text", "") or "")
    except UtteranceValidationError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)

    try:
        submit_text(room.pk, text, started_at=timezone.now())
    except RuntimeError:
        logger.exception("text queue unavailable: room=%s", room.pk)
        return JsonResponse({"detail": "Очередь обработки недоступна."}, status=503)

    return JsonResponse({"status": "accepted"}, status=202)


def _looks_like_audio(upload) -> bool:
    """Отсечь заведомо не аудио, не мешая браузерам без точного MIME."""
    content_type = (getattr(upload, "content_type", "") or "").split(";")[0].strip().lower()
    if content_type.startswith(("audio/", "video/webm")) or content_type in _ALLOWED_AUDIO_TYPES:
        return True
    name = (getattr(upload, "name", "") or "").lower()
    return any(name.endswith(suffix) for suffix in _ALLOWED_AUDIO_SUFFIXES)


@require_POST
def phrase_api(request: HttpRequest, join_code: str) -> JsonResponse:
    """Принять аудиофразу и распознать её в фоне (ТЗ 7.4, этап F6).

    Аудио читается в память и сразу закрывается как загруженный файл; ни
    ``Utterance``, ни временный файл медиа не создаются в HTTP-запросе. Ответ
    202 означает, что задание встало в очередь: ASR, глоссы и сохранение идут
    в фоновом обработчике.
    """
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Требуется вход."}, status=401)

    room = find_open_room(join_code)
    if room is None:
        return JsonResponse({"detail": "Комната не найдена или закрыта."}, status=404)
    if not _can_send_text(request.user, room):
        return JsonResponse(
            {"detail": "Отправлять фразы может только преподаватель этой комнаты."},
            status=403,
        )

    upload = request.FILES.get("audio") or request.FILES.get("file")
    if upload is None:
        return JsonResponse(
            {"detail": "Ожидался multipart-файл аудио в поле audio."},
            status=400,
        )
    if not _looks_like_audio(upload):
        upload.close()
        return JsonResponse({"detail": "Файл не похож на аудио."}, status=400)

    size = getattr(upload, "size", None)
    if size is not None and size > MAX_PHRASE_AUDIO_BYTES:
        upload.close()
        return JsonResponse({"detail": "Аудиофраза слишком большая."}, status=413)

    try:
        audio = upload.read(MAX_PHRASE_AUDIO_BYTES + 1)
    finally:
        # Закрываем и удаляем временный файл, если Django успел его создать.
        upload.close()
    if not audio:
        return JsonResponse({"detail": "Аудиофраза пустая."}, status=400)
    if len(audio) > MAX_PHRASE_AUDIO_BYTES:
        return JsonResponse({"detail": "Аудиофраза слишком большая."}, status=413)

    try:
        submit_audio(room.pk, audio, started_at=timezone.now())
    except (RuntimeError, ValueError):
        logger.exception("audio queue unavailable: room=%s", room.pk)
        return JsonResponse({"detail": "Очередь обработки недоступна."}, status=503)

    return JsonResponse({"status": "accepted"}, status=202)
