"""Маршруты интерфейса эксперта (монтируются под `/dictionary/`)."""

from django.urls import path

from dictionary import views

app_name = "dictionary"

urlpatterns = [
    path("review/", views.review_queue, name="review-queue"),
    path("review/<int:sign_id>/", views.review_sign, name="review-sign"),
    path("queue/", views.unknown_queue, name="unknown-queue"),
    path("queue/<int:word_id>/action/", views.unknown_word_action, name="unknown-word-action"),
]
