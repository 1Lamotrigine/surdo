"""HTTP-представления приложения dictionary: клипы и интерфейс эксперта."""

from __future__ import annotations

from django.conf import settings
from django.contrib import messages
from django.http import FileResponse, Http404, HttpRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.templatetags.static import static
from django.views.decorators.http import condition, require_http_methods

from dictionary.models import (
    Language,
    Sign,
    SignClip,
    SignStatus,
    UnknownWord,
    UnknownWordStatus,
)
from dictionary.permissions import dictionary_required, review_required
from dictionary.services import (
    SignPermissionError,
    SignValidationError,
    UnknownWordValidationError,
    list_unknown_words,
    mark_unknown_word_recorded,
    queue_unknown_word,
    reject_sign,
    verify_sign,
)
from services.clips import default_storage

# Клипы неизменяемы (новая версия — новый файл), поэтому кэш надолго.
CLIP_CACHE_CONTROL = "public, max-age=604800, immutable"
CLIP_CONTENT_TYPE = "application/gzip"
# Анимационные клипы (H1): VRMA — это тоже GLB-контейнер.
ANIMATION_CONTENT_TYPES = {
    "vrma": "model/gltf-binary",
    "glb": "model/gltf-binary",
}
DEFAULT_ANIMATION_CONTENT_TYPE = "application/octet-stream"


def _mediapipe_wasm_path() -> str:
    """Каталог WASM MediaPipe: Vite dev-сервер или собранная статика.

    В dev-режиме модули и WASM отдаёт Vite (`npm run dev`), в остальных случаях —
    `static/dist/mediapipe`, куда плагин Vite копирует файлы при сборке.
    """
    config = settings.DJANGO_VITE["default"]
    prefix = config.get("static_url_prefix", "dist")
    if config.get("dev_mode"):
        host = config.get("dev_server_host", "localhost")
        port = config.get("dev_server_port", 5173)
        return f"http://{host}:{port}/{settings.STATIC_URL.strip('/')}/{prefix}/mediapipe"
    return static(f"{prefix}/mediapipe")


def _get_clip(clip_id: int) -> SignClip | None:
    return SignClip.objects.filter(pk=clip_id).first()


def _clip_etag(request: HttpRequest, clip_id: int, ext: str | None = None, **kwargs) -> str | None:
    clip = _get_clip(clip_id)
    if clip is None or not clip.file:
        return None
    try:
        return default_storage.etag(clip.file.name)
    except FileNotFoundError:
        # Вью ниже отдаст 404: ETag для отсутствующего файла не считаем.
        return None


@condition(etag_func=_clip_etag)
def clip_file(request: HttpRequest, clip_id: int, ext: str | None = None) -> FileResponse:
    """Отдать файл клипа с ETag и кэш-заголовками (повтор — 304).

    В проде запросы к ``/media/clips/<id>.json.gz`` перехватывает Caddy; эта вью
    используется, когда клипы отдаёт Django (DEBUG, тесты). Для анимаций (H1)
    тип ответа зависит от расширения: ``.vrma``/``.glb`` — ``model/gltf-binary``.
    """
    clip = _get_clip(clip_id)
    if clip is None or not clip.file:
        raise Http404("Клип не найден")

    try:
        file = default_storage.open(clip.file.name)
    except FileNotFoundError as exc:
        raise Http404("Файл клипа отсутствует") from exc

    if clip.is_animation:
        content_type = ANIMATION_CONTENT_TYPES.get(
            (ext or clip.file_ext).lower(), DEFAULT_ANIMATION_CONTENT_TYPE
        )
    else:
        content_type = CLIP_CONTENT_TYPE
    response = FileResponse(file, content_type=content_type)
    response["Cache-Control"] = CLIP_CACHE_CONTROL
    return response


@review_required
def review_queue(request: HttpRequest):
    """Очередь жестов на проверке (интерфейс эксперта, FR-20).

    Показываем жесты в статусе ``review``: эксперт открывает карточку, смотрит
    клип и утверждает или отклоняет с комментарием.
    """
    signs = (
        Sign.objects.filter(status=SignStatus.REVIEW)
        .select_related("recorded_by")
        .order_by("created_at")
    )
    return render(request, "dictionary/review_queue.html", {"signs": signs})


@require_http_methods(["GET", "POST"])
@review_required
def review_sign(request: HttpRequest, sign_id: int):
    """Карточка жеста: эксперт смотрит клип и принимает решение (FR-20).

    GET показывает клип и форму решения, POST применяет решение через сервисные
    переходы B4 (утверждение растит версию словаря).
    """
    sign = get_object_or_404(
        Sign.objects.select_related("recorded_by", "verified_by"), pk=sign_id
    )

    if request.method == "POST":
        decision = request.POST.get("decision")
        comment = request.POST.get("comment", "")
        if decision == "approve":
            action, verb = verify_sign, "утверждён"
        elif decision == "reject":
            action, verb = reject_sign, "отклонён"
        else:
            messages.error(request, "Выберите решение: утвердить или отклонить.")
            return redirect("dictionary:review-sign", sign_id=sign.pk)

        try:
            action(sign, actor=request.user, comment=comment)
        except SignPermissionError as exc:
            messages.error(request, str(exc))
        except SignValidationError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, f"Жест «{sign.gloss}» {verb}.")
        return redirect("dictionary:review-queue")

    return render(
        request,
        "dictionary/review_sign.html",
        {
            "sign": sign,
            "best_clip": sign.best_clip,
        },
    )


@dictionary_required
def unknown_queue(request: HttpRequest):
    """Очередь нераспознанных слов для редактора (FR-21).

    Сверху самое частое слово: сколько раз встретилось и кнопка «Записать жест».
    """
    lang = request.GET.get("lang") or None
    if lang and lang not in Language.values:
        lang = None
    words = list_unknown_words(lang=lang)
    return render(
        request,
        "dictionary/unknown_queue.html",
        {"words": words, "lang": lang, "languages": Language.choices},
    )


@require_http_methods(["POST"])
@dictionary_required
def unknown_word_action(request: HttpRequest, word_id: int):
    """Взять слово в работу или пометить записанным (FR-21)."""
    word = get_object_or_404(UnknownWord, pk=word_id)
    action = request.POST.get("action")
    if action == "queue":
        transition, verb = queue_unknown_word, "взято в работу"
    elif action == "recorded":
        transition, verb = mark_unknown_word_recorded, "помечено записанным"
    else:
        messages.error(request, "Неизвестное действие со словом очереди.")
        return redirect("dictionary:unknown-queue")

    try:
        transition(word)
    except UnknownWordValidationError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"Слово «{word.lemma}» {verb}.")
    return redirect("dictionary:unknown-queue")


@dictionary_required
def record_gesture(request: HttpRequest):
    """Инструмент записи жеста (D1–D4): камера, клип и сохранение черновика.

    MediaPipe рисует скелет, D2 собирает клип, D3 даёт посмотреть его на
    аватаре, заполнить метаданные и отправить в ``POST /api/signs/``. D4
    открывает эту же страницу для слова из очереди: ``?word=<id>``
    подставляет глоссу и язык, а API после сохранения помечает слово
    записанным. Страница доступна ролям словаря, как и остальные инструменты
    редактора.
    """
    word = None
    raw_word_id = request.GET.get("word")
    if raw_word_id:
        try:
            word_id = int(raw_word_id)
        except (TypeError, ValueError) as exc:
            raise Http404("Слово очереди не найдено") from exc
        word = get_object_or_404(UnknownWord, pk=word_id)
        if word.status != UnknownWordStatus.QUEUED:
            if word.status == UnknownWordStatus.RECORDED:
                messages.info(request, f"Слово «{word.lemma}» уже записано.")
            else:
                messages.warning(request, f"Сначала возьмите слово «{word.lemma}» в работу.")
            return redirect("dictionary:unknown-queue")

    return render(
        request,
        "dictionary/record.html",
        {
            "model_url": settings.MEDIAPIPE_HOLISTIC_MODEL_URL,
            "avatar_model_url": settings.AVATAR_MODEL_URL,
            "mediapipe_wasm_path": _mediapipe_wasm_path(),
            "languages": Language.choices,
            "word": word,
            "fps": settings.CLIP_DEFAULT_FPS,
            "max_frames": settings.CLIP_MAX_FRAMES,
            "max_bytes": settings.CLIP_MAX_SIZE_BYTES,
            "max_duration_seconds": round(
                settings.CLIP_MAX_FRAMES / settings.CLIP_DEFAULT_FPS, 1
            ),
        },
    )
