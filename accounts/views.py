"""HTTP-представления аккаунтов: регистрация."""

from django.contrib import messages
from django.contrib.auth import login
from django.http import HttpRequest
from django.shortcuts import redirect, render

from accounts.forms import RegistrationForm


def register(request: HttpRequest):
    if request.user.is_authenticated:
        return redirect("home")

    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, "Аккаунт создан. Добро пожаловать!")
        return redirect("home")

    return render(request, "accounts/register.html", {"form": form})
