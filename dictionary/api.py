"""JSON API словаря: публичный список жестов, загрузка клипа и решение эксперта."""

from __future__ import annotations

import json

from django.conf import settings
from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_POST

from dictionary.models import Language, Sign, SignStatus, UnknownWord
from dictionary.permissions import can_manage_dictionary, can_review_signs
from dictionary.services import (
    SignPermissionError,
    SignValidationError,
    create_sign,
    dictionary_payload,
    reject_sign,
    sign_payload,
    unknown_word_payload,
    verify_sign,
)


@require_GET
def dictionary_api(request: HttpRequest) -> JsonResponse:
    """Публичный список проверенных жестов и версия словаря (ТЗ 7.4).

    ``?lang=rsl`` ограничивает язык. ``?status=draft`` отдаёт черновики —
    только для редактора, эксперта или администратора (FR-19: студентам их
    показывать нельзя, кроме демо-режима комнаты).
    """
    lang = request.GET.get("lang") or None
    if lang and lang not in Language.values:
        return JsonResponse({"detail": f"Неизвестный язык: {lang}."}, status=400)

    status = request.GET.get("status") or SignStatus.VERIFIED
    if status not in SignStatus.values:
        return JsonResponse({"detail": f"Неизвестный статус: {status}."}, status=400)

    if status != SignStatus.VERIFIED and not can_manage_dictionary(request.user):
        return JsonResponse({"detail": "Нет доступа к непроверенным жестам."}, status=403)

    payload = dictionary_payload(lang=lang, include_drafts=status != SignStatus.VERIFIED)
    return JsonResponse(payload)


@require_POST
def create_sign_api(request: HttpRequest) -> JsonResponse:
    """Создать жест редактором: метаданные и файл клипа (ТЗ 7.4).

    Принимает ``multipart/form-data`` (поля ``gloss``, ``lang``, ``description``,
    файл ``clip`` или файл ``animation``, необязательный ``unknown_word``) или
    ``application/json``. ``clip`` — запись с камеры (``.json.gz``, landmarks),
    ``animation`` — готовая анимация (``.vrma``/``.glb``); оба сразу нельзя.
    Если передан ``unknown_word``, слово очереди должно быть в статусе
    ``queued`` и после успешного создания жеста становится ``recorded`` (D4).
    """
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Требуется вход."}, status=401)
    if not can_manage_dictionary(request.user):
        return JsonResponse(
            {"detail": "Создавать жесты может только редактор."},
            status=403,
        )

    if request.content_type == "application/json":
        try:
            payload = json.loads(request.body or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JsonResponse({"detail": "Некорректный JSON."}, status=400)
        if not isinstance(payload, dict):
            return JsonResponse({"detail": "Ожидался JSON-объект."}, status=400)
        gloss = payload.get("gloss", "")
        lang = payload.get("lang")
        description = payload.get("description", "")
        source = payload
        clip = None
        animation = None
        animation_name = ""
        animation_clip_name = ""
    else:
        gloss = request.POST.get("gloss", "")
        lang = request.POST.get("lang")
        description = request.POST.get("description", "")
        source = request.POST
        upload = request.FILES.get("clip")
        clip = None
        if upload is not None:
            if upload.size > settings.CLIP_MAX_SIZE_BYTES:
                return JsonResponse(
                    {"detail": f"Файл клипа больше {settings.CLIP_MAX_SIZE_BYTES} байт."},
                    status=413,
                )
            clip = upload.read()

        animation = None
        animation_name = ""
        animation_upload = request.FILES.get("animation")
        animation_clip_name = request.POST.get("animation_clip", "")
        if animation_upload is not None:
            if animation_upload.size > settings.CLIP_MAX_ANIMATION_BYTES:
                return JsonResponse(
                    {
                        "detail": (
                            "Файл анимации больше "
                            f"{settings.CLIP_MAX_ANIMATION_BYTES} байт."
                        )
                    },
                    status=413,
                )
            animation = animation_upload.read()
            animation_name = animation_upload.name or ""

    if clip is not None and animation is not None:
        return JsonResponse(
            {"detail": "Передайте либо клип landmarks, либо анимацию, но не оба."},
            status=400,
        )

    unknown_word = None
    raw_unknown_word = source.get("unknown_word")
    if raw_unknown_word not in (None, ""):
        try:
            unknown_word_id = int(raw_unknown_word)
        except (TypeError, ValueError):
            return JsonResponse({"detail": "Некорректный id слова очереди."}, status=400)
        try:
            unknown_word = UnknownWord.objects.get(pk=unknown_word_id)
        except UnknownWord.DoesNotExist:
            return JsonResponse({"detail": "Слово очереди не найдено."}, status=404)

    try:
        sign = create_sign(
            recorded_by=request.user,
            gloss=gloss,
            lang=lang,
            description=description,
            clip=clip,
            animation=animation,
            animation_name=animation_name,
            animation_clip=animation_clip_name,
            unknown_word=unknown_word,
        )
    except SignValidationError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)

    result = sign_payload(sign)
    if unknown_word is not None:
        result["unknown_word"] = unknown_word_payload(unknown_word)
    return JsonResponse(result, status=201)


# Допустимые решения эксперта: утвердить или отклонить.
APPROVE = "approve"
REJECT = "reject"
DECISIONS = {APPROVE, REJECT}


@require_POST
def review_sign_api(request: HttpRequest, sign_id: int) -> JsonResponse:
    """Решение эксперта по жесту (ТЗ 7.4): ``approve`` или ``reject``.

    Принимает JSON ``{"decision": "approve"|"reject", "comment": "..."}`` или
    поля формы. Утверждать и отклонять может только эксперт-носитель (или
    администратор); иначе 401/403.
    """
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Требуется вход."}, status=401)
    if not can_review_signs(request.user):
        return JsonResponse(
            {"detail": "Менять статус жеста может только эксперт-носитель."},
            status=403,
        )

    if request.content_type == "application/json":
        try:
            payload = json.loads(request.body or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JsonResponse({"detail": "Некорректный JSON."}, status=400)
        if not isinstance(payload, dict):
            return JsonResponse({"detail": "Ожидался JSON-объект."}, status=400)
    else:
        payload = request.POST

    decision = payload.get("decision")
    comment = payload.get("comment", "") or ""

    if decision not in DECISIONS:
        return JsonResponse(
            {"detail": "Решение должно быть 'approve' или 'reject'."},
            status=400,
        )

    sign = get_object_or_404(Sign, pk=sign_id)
    action = verify_sign if decision == APPROVE else reject_sign
    try:
        sign = action(sign, actor=request.user, comment=comment)
    except SignPermissionError as exc:
        return JsonResponse({"detail": str(exc)}, status=403)
    except SignValidationError as exc:
        return JsonResponse({"detail": str(exc)}, status=409)

    return JsonResponse(sign_payload(sign))
