"""Форма создания комнаты."""

from django import forms

from rooms.models import Room


class RoomForm(forms.ModelForm):
    class Meta:
        model = Room
        fields = ("title", "demo_mode")
        labels = {
            "title": "Название комнаты",
            "demo_mode": "Демо-режим",
        }
        widgets = {
            "title": forms.TextInput(
                attrs={
                    "autofocus": True,
                    "placeholder": "Например: Алгебра, 10 класс",
                    "maxlength": 200,
                }
            ),
        }
        help_texts = {
            "demo_mode": (
                "Показывать в комнате непроверенные жесты с пометкой "
                "«прототип, жест не проверен носителем»."
            ),
        }
