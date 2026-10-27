"""Админка словаря жестов: жесты, клипы, версии словаря, очередь слов."""

from __future__ import annotations

from django.contrib import admin
from django.utils.html import format_html

from dictionary.models import (
    DictionaryVersion,
    Sign,
    SignClip,
    UnknownWord,
)
from dictionary.services import (
    SignPermissionError,
    SignValidationError,
    UnknownWordValidationError,
    mark_unknown_word_recorded,
    queue_unknown_word,
    reject_sign,
    submit_for_review,
    verify_sign,
)


class SignClipInline(admin.TabularInline):
    """Клипы жеста: метаданные и ссылка на файл."""

    model = SignClip
    extra = 0
    fields = (
        "version",
        "fps",
        "frames",
        "duration_ms",
        "size_bytes",
        "created_at",
        "clip_link",
    )
    readonly_fields = (
        "version",
        "fps",
        "frames",
        "duration_ms",
        "size_bytes",
        "created_at",
        "clip_link",
    )
    can_delete = False
    show_change_link = True

    @admin.display(description="файл клипа")
    def clip_link(self, obj: SignClip) -> str:
        if not obj.pk or not obj.file:
            return "—"
        url = obj.file_url()
        size_kb = obj.size_bytes / 1024
        return format_html(
            '<a href="{}" target="_blank" rel="noopener">открыть</a> ({} КБ)',
            url,
            f"{size_kb:.1f}",
        )


@admin.register(Sign)
class SignAdmin(admin.ModelAdmin):
    list_display = (
        "gloss",
        "lang",
        "status",
        "clips_count",
        "recorded_by",
        "verified_by",
        "verified_at",
        "updated_at",
    )
    list_filter = ("status", "lang")
    search_fields = ("gloss", "description", "comment")
    list_select_related = ("recorded_by", "verified_by")
    readonly_fields = (
        "created_at",
        "updated_at",
        "verified_at",
        "clip_preview",
    )
    inlines = (SignClipInline,)
    actions = ("submit_for_review_action", "verify_action", "reject_action")

    fieldsets = (
        (None, {"fields": ("gloss", "lang", "status", "description")}),
        ("Проверка", {"fields": ("recorded_by", "verified_by", "verified_at", "comment")}),
        ("Клипы", {"fields": ("clip_preview",)}),
        ("Даты", {"fields": ("created_at", "updated_at")}),
    )

    @admin.display(description="клипов")
    def clips_count(self, obj: Sign) -> int:
        return obj.clips.count()

    @admin.display(description="предпросмотр клипа")
    def clip_preview(self, obj: Sign) -> str:
        """Показать ссылку на лучший клип и его параметры.

        Полноценный просмотр анимации — в браузере на этапе C; здесь для ручной
        проверки достаточно открыть файл клипа и увидеть метаданные.
        """
        if not obj.pk:
            return "—"
        clip = obj.best_clip
        if clip is None:
            return "Клипа пока нет."
        link = format_html(
            '<a href="{}" target="_blank" rel="noopener">Открыть клип №{}</a>',
            clip.file_url(),
            clip.pk,
        )
        return format_html(
            "{} — кадров: {}, fps: {}, длительность: {} мс, версия: {}, размер: {} КБ",
            link,
            clip.frames,
            clip.fps,
            clip.duration_ms,
            clip.version,
            f"{clip.size_bytes / 1024:.1f}",
        )

    # --- Действия со статусами (переиспользуют сервисные переходы B4) ---

    @admin.action(description="Отправить на проверку")
    def submit_for_review_action(self, request, queryset):
        self._apply_transition(request, queryset, submit_for_review, "отправлено на проверку")

    @admin.action(description="Утвердить (эксперт)")
    def verify_action(self, request, queryset):
        self._apply_transition(request, queryset, verify_sign, "утверждено")

    @admin.action(description="Отклонить (эксперт)")
    def reject_action(self, request, queryset):
        self._apply_transition(request, queryset, reject_sign, "отклонено")

    def _apply_transition(self, request, queryset, func, verb: str) -> None:
        done = 0
        skipped = 0
        for sign in queryset:
            try:
                func(sign, actor=request.user, comment=sign.comment)
            except (SignValidationError, SignPermissionError) as exc:
                skipped += 1
                self.message_user(
                    request,
                    f"«{sign.gloss}»: {exc}",
                    level="warning",
                )
            else:
                done += 1
        self.message_user(request, f"Жестов {verb}: {done}. Пропущено: {skipped}.")


@admin.register(SignClip)
class SignClipAdmin(admin.ModelAdmin):
    list_display = ("id", "sign", "version", "fps", "frames", "duration_ms", "size_bytes")
    list_filter = ("sign__lang", "sign__status", "fps")
    search_fields = ("sign__gloss",)
    list_select_related = ("sign",)
    readonly_fields = ("created_at", "clip_player")
    fields = (
        "sign",
        "file",
        "version",
        "fps",
        "frames",
        "duration_ms",
        "size_bytes",
        "created_at",
        "clip_player",
    )

    @admin.display(description="просмотр клипа")
    def clip_player(self, obj: SignClip) -> str:
        if not obj.pk or not obj.file:
            return "—"
        return format_html(
            '<a href="{}" target="_blank" rel="noopener">Открыть файл клипа</a>',
            obj.file_url(),
        )


@admin.register(UnknownWord)
class UnknownWordAdmin(admin.ModelAdmin):
    list_display = ("lemma", "lang", "count", "status", "last_seen_at", "created_at")
    list_filter = ("status", "lang")
    search_fields = ("lemma",)
    readonly_fields = ("created_at",)
    ordering = ("-count", "lemma")
    actions = ("queue_words", "mark_words_recorded")

    @admin.action(description="Взять в работу")
    def queue_words(self, request, queryset):
        self._apply(request, queryset, queue_unknown_word, "взяты в работу")

    @admin.action(description="Пометить записанными")
    def mark_words_recorded(self, request, queryset):
        self._apply(request, queryset, mark_unknown_word_recorded, "помечены записанными")

    def _apply(self, request, queryset, func, verb: str) -> None:
        done = 0
        skipped = 0
        for word in queryset:
            try:
                func(word)
            except UnknownWordValidationError as exc:
                skipped += 1
                self.message_user(request, f"«{word.lemma}»: {exc}", level="warning")
            else:
                done += 1
        self.message_user(request, f"Слов {verb}: {done}. Пропущено: {skipped}.")


@admin.register(DictionaryVersion)
class DictionaryVersionAdmin(admin.ModelAdmin):
    list_display = ("lang", "number", "created_at", "signs_at_version")
    list_filter = ("lang",)
    readonly_fields = ("created_at",)
    ordering = ("lang", "-number")

    @admin.display(description="текущая")
    def signs_at_version(self, obj: DictionaryVersion) -> str:
        return "да" if obj == DictionaryVersion.current(obj.lang) else "нет"

    def has_add_permission(self, request) -> bool:
        # Версии создаёт сервис при утверждении жеста (B4), вручную не заводим.
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False
