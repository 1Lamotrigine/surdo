"""Сервисные функции словаря: выборка жестов и создание жеста с клипом."""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from dictionary.models import (
    DictionaryVersion,
    Language,
    Sign,
    SignClip,
    SignStatus,
    UnknownWord,
    UnknownWordStatus,
)
from dictionary.queue import UnknownWordTransitionError
from dictionary.queue import validate_transition as validate_word_transition
from dictionary.statuses import (
    ROLE_EDITOR,
    ROLE_EXPERT,
    StatusTransitionError,
    allowed_targets,
    validate_transition,
)
from services.clips import ClipFormatError, ClipMeta, default_storage, parse_clip

# Глоссы, которые отдаём в публичном списке по умолчанию.
PUBLIC_STATUS = SignStatus.VERIFIED


class SignValidationError(ValueError):
    """Метаданные жеста или клипа не прошли проверку."""


class SignPermissionError(PermissionError):
    """У пользователя нет роли для запрошенного действия."""


def list_signs(*, lang: str | None = None, status: str = PUBLIC_STATUS) -> list[Sign]:
    """Жесты словаря по языку и статусу (для публичного списка и админки).

    По умолчанию отдаём только проверенные жесты — их видят студенты. В
    демо-режиме комнаты клиент запрашивает и черновики (``status=draft``).
    """
    queryset = Sign.objects.all()
    if lang:
        queryset = queryset.filter(lang=lang)
    if status:
        queryset = queryset.filter(status=status)
    return list(queryset.order_by("gloss"))


def sign_payload(sign: Sign, *, include_unverified_clip: bool = False) -> dict:
    """Представление жеста для HTTP API: глосса, статус и ссылки на клипы."""
    clips = [clip for clip in sign.clips.all()]
    best = sign.best_clip
    payload = {
        "id": sign.pk,
        "gloss": sign.gloss,
        "lang": sign.lang,
        "status": sign.status,
        "description": sign.description,
        "verified": sign.is_verified,
        "comment": sign.comment,
        # Куда можно перевести жест дальше (для интерфейса редактора и эксперта).
        "allowed_transitions": sorted(allowed_targets(sign.status)),
        "clips": [
            {
                "id": clip.pk,
                "version": clip.version,
                "fps": clip.fps,
                "frames": clip.frames,
                "duration_ms": clip.duration_ms,
                "url": clip.file_url(),
            }
            for clip in clips
        ],
    }
    if best is not None:
        payload["best_clip_id"] = best.pk
    elif include_unverified_clip:
        payload["best_clip_id"] = None
    return payload


def dictionary_payload(*, lang: str | None = None, include_drafts: bool = False) -> dict:
    """Список жестов и версия словаря для ``GET /api/dictionary/``.

    Проверенные жесты видны всем; черновики (``include_drafts=True``) — только
    для демо-режима комнаты.
    """
    signs = list_signs(lang=lang, status=PUBLIC_STATUS)
    if include_drafts:
        signs += list_signs(lang=lang, status=SignStatus.DRAFT)
    version = DictionaryVersion.current(lang) if lang else None
    return {
        "lang": lang,
        "version": version.number if version else None,
        "signs": [sign_payload(sign) for sign in signs],
    }


def _clean_gloss(gloss: str) -> str:
    cleaned = " ".join((gloss or "").split())
    if not cleaned:
        raise SignValidationError("Укажите глоссу жеста.")
    if len(cleaned) > 100:
        raise SignValidationError("Глосса длиннее 100 символов.")
    return cleaned


def _clean_lang(lang: str | None) -> str:
    if not lang:
        return Language.RSL
    if lang not in Language.values:
        raise SignValidationError(f"Неизвестный язык: {lang}.")
    return lang


def create_sign(
    *,
    recorded_by,
    gloss: str,
    lang: str | None = None,
    description: str = "",
    clip: bytes | None = None,
    status: str = SignStatus.DRAFT,
    unknown_word: UnknownWord | None = None,
) -> Sign:
    """Создать жест редактора и, если передан файл, приложить к нему клип.

    Клип сохраняется в хранилище (``services.clips``) и его путь и метаданные
    записываются в ``SignClip``. Формат клипа проверяется до записи на диск.

    Если передан ``unknown_word`` (D4), слово должно быть взято в работу
    (``queued``): в той же транзакции оно становится ``recorded``. Так слово
    очереди не теряется, если создание жеста или клипа не удалось.
    """
    gloss = _clean_gloss(gloss)
    lang = _clean_lang(lang)
    if status not in SignStatus.values:
        raise SignValidationError(f"Неизвестный статус: {status}.")
    if unknown_word is not None and unknown_word.status != UnknownWordStatus.QUEUED:
        raise SignValidationError(
            f"Слово «{unknown_word.lemma}» нужно сначала взять в работу."
        )

    meta: ClipMeta | None = None
    if clip is not None:
        try:
            meta = parse_clip(clip)
        except ClipFormatError as exc:
            raise SignValidationError(str(exc)) from exc

    with transaction.atomic():
        sign = Sign.objects.create(
            gloss=gloss,
            lang=lang,
            description=description or "",
            status=status,
            recorded_by=recorded_by if getattr(recorded_by, "is_authenticated", False) else None,
        )
        if clip is not None and meta is not None:
            _attach_clip(sign, clip, meta)
        if unknown_word is not None:
            try:
                mark_unknown_word_recorded(unknown_word)
            except UnknownWordValidationError as exc:
                raise SignValidationError(str(exc)) from exc
    return sign


def _has_role(user, role: str) -> bool:
    """Может ли пользователь выполнить переход с требуемой ролью.

    Редактор словаря и администратор закрывают роль редактора; эксперт-носитель и
    администратор — роль эксперта (админ может всё, как в остальном проекте).
    """
    if not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_admin", False):
        return True
    if role == ROLE_EXPERT:
        return bool(getattr(user, "is_expert", False))
    if role == ROLE_EDITOR:
        return bool(getattr(user, "is_editor", False) or getattr(user, "is_expert", False))
    return False


def transition_sign(
    sign: Sign,
    *,
    to_status: str,
    actor,
    comment: str = "",
) -> Sign:
    """Перевести жест в новый статус по правилам ``dictionary.statuses``.

    Проверяет, что переход разрешён и у ``actor`` есть нужная роль (редактор для
    отправки на ревью, эксперт для утверждения/отклонения). При переходе в
    ``verified`` фиксируется проверяющий и растёт версия словаря языка.
    Возвращает обновлённый жест.
    """
    if to_status not in SignStatus.values:
        raise SignValidationError(f"Неизвестный статус: {to_status}.")

    try:
        required = validate_transition(sign.status, to_status)
    except StatusTransitionError as exc:
        raise SignValidationError(str(exc)) from exc

    if not _has_role(actor, required):
        raise SignPermissionError(
            "Утверждать и отклонять жесты может только эксперт-носитель."
            if required == ROLE_EXPERT
            else "Отправлять жесты на проверку может только редактор словаря."
        )

    with transaction.atomic():
        _apply_status(sign, to_status=to_status, actor=actor, comment=comment)
        if to_status == SignStatus.VERIFIED:
            DictionaryVersion.bump(sign.lang)
    return sign


def _apply_status(sign: Sign, *, to_status: str, actor, comment: str) -> None:
    """Записать новый статус жеста и связанные с ним поля."""
    sign.status = to_status
    fields = ["status", "updated_at"]
    if comment:
        sign.comment = comment
        fields.append("comment")
    if to_status == SignStatus.VERIFIED:
        sign.verified_by = actor
        sign.verified_at = timezone.now()
        fields += ["verified_by", "verified_at"]
    sign.save(update_fields=fields)


def submit_for_review(sign: Sign, *, actor, comment: str = "") -> Sign:
    """Отправить жест на проверку (редактор): ``draft``/``rejected`` → ``review``."""
    return transition_sign(sign, to_status=SignStatus.REVIEW, actor=actor, comment=comment)


def verify_sign(sign: Sign, *, actor, comment: str = "") -> Sign:
    """Утвердить жест (эксперт): ``review`` → ``verified`` плюс версия словаря."""
    return transition_sign(sign, to_status=SignStatus.VERIFIED, actor=actor, comment=comment)


def reject_sign(sign: Sign, *, actor, comment: str = "") -> Sign:
    """Отклонить жест (эксперт): ``review``/``verified`` → ``rejected``."""
    return transition_sign(sign, to_status=SignStatus.REJECTED, actor=actor, comment=comment)


def _attach_clip(sign: Sign, blob: bytes, meta: ClipMeta) -> SignClip:
    """Сохранить файл клипа в хранилище и создать запись ``SignClip``."""
    name = _clip_filename(sign, meta)
    stamp = timezone.now().strftime("%Y/%m")
    path = f"clips/{stamp}/{name}"
    default_storage.save(path, blob)
    return SignClip.objects.create(
        sign=sign,
        file=path,
        fps=meta.fps,
        duration_ms=meta.duration_ms,
        frames=meta.frames,
        version=sign.clips.count() + 1,
        size_bytes=len(blob),
    )


def _clip_filename(sign: Sign, meta: ClipMeta) -> str:
    """Имя файла клипа: id жеста, транслит глоссы и версия формата."""
    slug = _ascii_slug(sign.gloss) or "sign"
    return f"{sign.pk}-{slug}-v{meta.version}.json.gz"


def _ascii_slug(value: str) -> str:
    """ASCII-слаг из глоссы (латиница, цифры, дефис)."""
    translit = {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
        "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
        "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
        "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
        "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    }
    chars: list[str] = []
    for char in value.lower():
        if char.isascii() and (char.isalnum() or char in "-_"):
            chars.append(char)
        elif char in translit:
            chars.append(translit[char])
        elif chars and chars[-1] != "-":
            chars.append("-")
    slug = "".join(chars).strip("-")
    # Убираем повторные дефисы.
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug[:60]


# --- Очередь нераспознанных слов (B7) --------------------------------------


class UnknownWordValidationError(ValueError):
    """Нераспознанное слово не прошло проверку."""


def _clean_lemma(lemma: str) -> str:
    cleaned = " ".join((lemma or "").split())
    if not cleaned:
        raise UnknownWordValidationError("Пустая лемма не добавляется в очередь.")
    if len(cleaned) > 100:
        raise UnknownWordValidationError("Лемма длиннее 100 символов.")
    return cleaned


def _clean_word_lang(lang: str | None) -> str:
    if not lang:
        return Language.RSL
    if lang not in Language.values:
        raise UnknownWordValidationError(f"Неизвестный язык: {lang}.")
    return lang


def record_unknown_word(
    lemma: str,
    *,
    lang: str | None = None,
) -> UnknownWord:
    """Добавить нераспознанное слово в очередь, агрегируя повторы (FR-9).

    Повторы по ``(lemma, lang)`` увеличивают ``count`` и обновляют
    ``last_seen_at``. Уже записанное слово (``recorded``) повторно не всплывает:
    счётчик растёт, но статус остаётся ``recorded``.
    """
    cleaned = _clean_lemma(lemma)
    lang = _clean_word_lang(lang)
    word, created = UnknownWord.objects.get_or_create(
        lemma=cleaned,
        lang=lang,
        defaults={"count": 1, "last_seen_at": timezone.now()},
    )
    if not created:
        word.count += 1
        word.last_seen_at = timezone.now()
        word.save(update_fields=("count", "last_seen_at"))
    return word


def record_unknown_words(lemmas, *, lang: str | None = None) -> list[UnknownWord]:
    """Записать в очередь список лемм (например, из объекта глосс)."""
    return [record_unknown_word(lemma, lang=lang) for lemma in lemmas]


def list_unknown_words(
    *,
    lang: str | None = None,
    status: str | None = None,
    include_recorded: bool = False,
) -> list[UnknownWord]:
    """Очередь нераспознанных слов для редактора.

    По умолчанию отдаём слова, которые ещё не записаны (``new`` и ``queued``),
    сверху самые частые (FR-21). ``include_recorded=True`` добавляет уже
    записанные для контроля.
    """
    queryset = UnknownWord.objects.all()
    if lang:
        queryset = queryset.filter(lang=lang)
    if status:
        queryset = queryset.filter(status=status)
    elif not include_recorded:
        queryset = queryset.exclude(status=UnknownWordStatus.RECORDED)
    return list(queryset.order_by("-count", "lemma"))


def unknown_word_payload(word: UnknownWord) -> dict:
    """Представление слова очереди для API и интерфейса."""
    return {
        "id": word.pk,
        "lemma": word.lemma,
        "lang": word.lang,
        "count": word.count,
        "status": word.status,
        "last_seen_at": word.last_seen_at.isoformat(),
    }


def transition_unknown_word(word: UnknownWord, *, to_status: str) -> UnknownWord:
    """Перевести слово по статусам ``new`` → ``queued`` → ``recorded`` (FR-21).

    Бросает ``UnknownWordValidationError`` для неизвестного или запрещённого
    перехода.
    """
    if to_status not in UnknownWordStatus.values:
        raise UnknownWordValidationError(f"Неизвестный статус: {to_status}.")
    try:
        validate_word_transition(word.status, to_status)
    except UnknownWordTransitionError as exc:
        raise UnknownWordValidationError(str(exc)) from exc

    word.status = to_status
    word.save(update_fields=("status",))
    return word


def queue_unknown_word(word: UnknownWord) -> UnknownWord:
    """Взять слово в работу: ``new``/``recorded`` → ``queued``."""
    return transition_unknown_word(word, to_status=UnknownWordStatus.QUEUED)


def mark_unknown_word_recorded(word: UnknownWord) -> UnknownWord:
    """Пометить слово записанным: ``queued`` → ``recorded`` (D4)."""
    return transition_unknown_word(word, to_status=UnknownWordStatus.RECORDED)
