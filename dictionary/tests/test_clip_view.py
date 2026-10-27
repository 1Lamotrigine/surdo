"""Раздача файла клипа: ETag, кэш-заголовки и 304 на повторный запрос."""

from pathlib import Path

import pytest
from django.urls import reverse

from dictionary.models import Language, Sign, SignClip

pytestmark = pytest.mark.django_db

PAYLOAD = b'\x1f\x8b\x08\x00{"version": 1, "gloss": "UCH"}'


@pytest.fixture
def clip(settings, tmp_path, django_user_model):
    settings.MEDIA_ROOT = tmp_path
    editor = django_user_model.objects.create_user(
        email="editor@example.com",
        password="StrongPass-12345",
        name="Редактор",
    )
    sign = Sign.objects.create(gloss="УЧЕБНИК", lang=Language.RSL, recorded_by=editor)
    relative = "clips/2026/10/uch.json.gz"
    target = Path(tmp_path) / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(PAYLOAD)
    return SignClip.objects.create(sign=sign, file=relative, frames=54, version=1)


def test_clip_is_served_with_content(client, clip):
    response = client.get(reverse("clip-file", args=[clip.pk]))

    assert response.status_code == 200
    assert b"".join(response.streaming_content) == PAYLOAD


def test_clip_response_has_cache_headers(client, clip):
    response = client.get(reverse("clip-file", args=[clip.pk]))

    assert response["Cache-Control"] == "public, max-age=604800, immutable"
    assert response["ETag"].startswith('"')


def test_second_request_with_etag_returns_304(client, clip):
    first = client.get(reverse("clip-file", args=[clip.pk]))
    etag = first["ETag"]

    second = client.get(reverse("clip-file", args=[clip.pk]), headers={"If-None-Match": etag})

    assert second.status_code == 304
    assert second.content == b""


def test_etag_differs_between_clips(client, clip):
    from pathlib import Path as _Path

    from django.conf import settings

    other_path = "clips/2026/10/other.json.gz"
    target = _Path(settings.MEDIA_ROOT) / other_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(PAYLOAD + b" ")
    other = SignClip.objects.create(sign=clip.sign, file=other_path, version=2)

    first = client.get(reverse("clip-file", args=[clip.pk]))
    second = client.get(reverse("clip-file", args=[other.pk]))

    assert first["ETag"] != second["ETag"]


def test_unknown_clip_returns_404(client, db):
    response = client.get(reverse("clip-file", args=[999999]))

    assert response.status_code == 404


def test_missing_file_returns_404(client, clip):
    from pathlib import Path as _Path

    from django.conf import settings

    (_Path(settings.MEDIA_ROOT) / clip.file.name).unlink()

    response = client.get(reverse("clip-file", args=[clip.pk]))

    assert response.status_code == 404
