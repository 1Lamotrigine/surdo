"""Админка комнат."""

from django.contrib import admin

from rooms.management import rotate_join_code
from rooms.models import Message, Participant, Room


class ParticipantInline(admin.TabularInline):
    model = Participant
    extra = 0
    fields = ("user", "guest_name", "session_key", "joined_at", "removed_at")
    readonly_fields = ("session_key", "joined_at")
    autocomplete_fields = ("user",)


class MessageInline(admin.TabularInline):
    model = Message
    extra = 0
    fields = ("author_name", "is_teacher", "body", "created_at")
    readonly_fields = ("author_name", "is_teacher", "body", "created_at")
    can_delete = False
    show_change_link = True


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = (
        "join_code",
        "title",
        "owner",
        "status",
        "demo_mode",
        "created_at",
        "closed_at",
    )
    list_filter = ("status", "demo_mode", "lang")
    search_fields = ("join_code", "title", "owner__email", "owner__name")
    list_select_related = ("owner",)
    readonly_fields = ("join_code", "created_at", "closed_at")
    inlines = (ParticipantInline, MessageInline)
    actions = ("close_rooms", "rotate_codes")

    @admin.action(description="Закрыть выбранные комнаты")
    def close_rooms(self, request, queryset):
        closed = 0
        for room in queryset.filter(status=Room.Status.OPEN):
            room.close()
            closed += 1
        self.message_user(request, f"Закрыто комнат: {closed}.")

    @admin.action(description="Сменить ID выбранных комнат")
    def rotate_codes(self, request, queryset):
        rotated = 0
        for room in queryset.filter(status=Room.Status.OPEN):
            rotate_join_code(room)
            rotated += 1
        self.message_user(request, f"Сменён ID у комнат: {rotated}.")


@admin.register(Participant)
class ParticipantAdmin(admin.ModelAdmin):
    list_display = ("display_name", "room", "user", "joined_at", "removed_at")
    list_filter = ("removed_at", "room__status")
    search_fields = ("guest_name", "user__email", "user__name", "room__join_code")
    list_select_related = ("room", "user")
    readonly_fields = ("joined_at",)
    autocomplete_fields = ("user",)


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("created_at", "room", "author_name", "is_teacher", "short_body")
    list_filter = ("is_teacher", "room__status")
    search_fields = ("author_name", "body", "room__join_code")
    list_select_related = ("room", "participant")
    readonly_fields = ("created_at",)

    @admin.display(description="текст")
    def short_body(self, obj: Message) -> str:
        return obj.body[:60]
