from __future__ import annotations

import pytest
from django.urls import reverse


def test_home_page_renders(client):
    response = client.get(reverse("home"))
    html = response.content.decode()

    assert response.status_code == 200
    assert "Лекция с аватаром" in html
    assert "text/html" in response["Content-Type"]
    assert "/static/dist/" in html


def test_htmx_demo_returns_fragment(client):
    response = client.get(reverse("htmx-demo"))

    assert response.status_code == 200
    assert "HTMX работает" in response.content.decode()
    assert "text/html" in response["Content-Type"]


@pytest.mark.django_db
def test_health_reports_database(client):
    response = client.get(reverse("health"))

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"database": "ok"}}
