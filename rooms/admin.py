"""Админка комнат."""

from django.contrib import admin

from rooms.models import Room


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
    actions = ("close_rooms",)

    @admin.action(description="Закрыть выбранные комнаты")
    def close_rooms(self, request, queryset):
        closed = 0
        for room in queryset.filter(status=Room.Status.OPEN):
            room.close()
            closed += 1
        self.message_user(request, f"Закрыто комнат: {closed}.")
