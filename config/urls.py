from django.contrib import admin
from django.urls import path

from config import views

urlpatterns = [
    path("", views.home, name="home"),
    path("health/", views.health, name="health"),
    path("partials/htmx-demo/", views.htmx_demo, name="htmx-demo"),
    path("admin/", admin.site.urls),
]
