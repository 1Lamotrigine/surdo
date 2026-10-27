"""QR-код и ссылка для входа в комнату."""

import segno

from rooms.models import Room


def room_join_path(join_code: str) -> str:
    return f"/r/{join_code}/"


def build_join_url(request, join_code: str) -> str:
    return request.build_absolute_uri(room_join_path(join_code))


def render_qr_svg(content: str) -> str:
    """Вернуть inline SVG с QR-кодом для вставки в шаблон."""
    qr = segno.make(content, error="m")
    return qr.svg_inline(
        scale=6,
        border=2,
        dark="#111827",
        light="#ffffff",
    )


def room_qr_svg(request, room: Room) -> str:
    return render_qr_svg(build_join_url(request, room.join_code))
