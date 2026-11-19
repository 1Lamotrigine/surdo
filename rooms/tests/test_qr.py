"""QR-код и ссылка для входа в комнату."""

import pytest

from rooms.qr import build_join_url, render_qr_svg, room_join_path, room_qr_svg
from rooms.services import create_room

pytestmark = pytest.mark.django_db


def test_room_join_path_uses_short_route():
    assert room_join_path("ABC234") == "/r/ABC234/"


def test_build_join_url_is_absolute(rf):
    request = rf.get("/")

    assert build_join_url(request, "ABC234") == "http://testserver/r/ABC234/"


def test_render_qr_svg_returns_inline_svg():
    svg = render_qr_svg("http://testserver/r/ABC234/")

    assert svg.startswith("<svg")
    assert "</svg>" in svg
    assert "<?xml" not in svg


def test_render_qr_svg_scales_with_container():
    """viewBox без width/height: иначе CSS не масштабирует SVG."""
    svg = render_qr_svg("http://testserver/r/ABC234/")

    assert 'viewBox="' in svg
    opening = svg[: svg.index(">")]
    assert "width=" not in opening
    assert "height=" not in opening


def test_room_qr_svg_encodes_short_link(owner, rf):
    room = create_room(owner=owner)
    request = rf.get("/")

    svg = room_qr_svg(request, room)

    assert "<svg" in svg
