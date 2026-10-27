"""Маршруты аккаунтов."""

from django.contrib.auth.views import LoginView, LogoutView
from django.urls import path

from accounts.forms import EmailAuthenticationForm
from accounts.views import register

app_name = "accounts"

urlpatterns = [
    path(
        "login/",
        LoginView.as_view(
            template_name="accounts/login.html",
            authentication_form=EmailAuthenticationForm,
            redirect_authenticated_user=True,
        ),
        name="login",
    ),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("register/", register, name="register"),
]
