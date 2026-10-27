"""Формы комнат: создание преподавателем и вход студента."""

from django import forms

from rooms.models import Room


class JoinCodeForm(forms.Form):
    """Ввод ID комнаты на главной странице."""

    join_code = forms.CharField(
        label="ID комнаты",
        max_length=6,
        widget=forms.TextInput(
            attrs={
                "autofocus": True,
                "placeholder": "Например, ABC234",
                "autocapitalize": "characters",
                "autocomplete": "off",
                "spellcheck": "false",
                "inputmode": "latin",
            }
        ),
    )

    def clean_join_code(self) -> str:
        code = self.cleaned_data["join_code"].strip().upper()
        if len(code) != 6:
            raise forms.ValidationError("ID комнаты состоит из 6 символов.")
        return code


class GuestNameForm(forms.Form):
    """Ввод имени студента при входе в комнату."""

    name = forms.CharField(
        label="Ваше имя",
        max_length=100,
        widget=forms.TextInput(
            attrs={
                "autofocus": True,
                "placeholder": "Как вас зовут?",
                "autocomplete": "name",
                "maxlength": 100,
            }
        ),
    )

    def clean_name(self) -> str:
        name = " ".join(self.cleaned_data["name"].split())
        if not name:
            raise forms.ValidationError("Укажите имя.")
        return name


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
