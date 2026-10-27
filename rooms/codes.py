"""Генерация коротких кодов для входа в комнату."""

import secrets

JOIN_CODE_LENGTH = 6

# Похожие символы O/0 и I/1 исключены: код должны легко читать и набирать.
JOIN_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def generate_join_code(length: int = JOIN_CODE_LENGTH) -> str:
    """Вернуть случайный код из разрешённых символов."""
    if length <= 0:
        raise ValueError("Длина кода должна быть положительной")
    return "".join(secrets.choice(JOIN_CODE_ALPHABET) for _ in range(length))
