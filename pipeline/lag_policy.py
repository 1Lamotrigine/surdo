"""Политика догона отставания (FR-16, этап F8).

Модуль описывает, что делать с показом при известном отставании: с какой
скоростью играть клипы, нужна ли пауза между ними и надо ли сжимать текст
следующей фразы. Пороги FR-15 остаются в ``pipeline.services`` (5 и 10 секунд),
а здесь только решения поверх уровня:

- ``green`` — обычная скорость, обычная пауза, без сжатия;
- ``yellow`` — лёгкое ускорение, короткая пауза, сжатие до 75%;
- ``red`` — максимум 1.3x, паузы нет, сжатие до 50%.

Функция ``lag_playback_policy`` чистая: её можно проверить без БД и очереди.
Именно её результат уходит студенту в событии ``utterance`` и в событии
``playback`` после ``display_started``. ``speed = None`` для зелёного уровня
означает «не трогать ручную скорость студента» (FR-13); на жёлтом и красном
клиент берёт максимум из ручной скорости и скорости догона, но не выше 1.3x.
"""

from __future__ import annotations

from dataclasses import dataclass

from pipeline.services import lag_level

# Скорости догона. Ручная настройка студента остаётся 0.6–1.2x, 1.3x — только
# внутренний предел FR-16.
LAG_YELLOW_SPEED = 1.15
LAG_RED_SPEED = 1.3

# Целевая длина сжатой фразы относительно исходной (F3: target_ratio).
LAG_YELLOW_TARGET_RATIO = 0.75
LAG_RED_TARGET_RATIO = 0.5

# Пауза в нейтральной позе между клипами. На красном уровне она исчезает:
# FR-16 требует пропускать паузы, чтобы догнать очередь.
LAG_GREEN_GAP_MS = 120
LAG_YELLOW_GAP_MS = 40
LAG_RED_GAP_MS = 0

# Короткие фразы сжимать бессмысленно: вызов LLM только добавит задержку.
LAG_COMPRESS_MIN_CHARS = 24


@dataclass(frozen=True)
class LagPlaybackPolicy:
    """Параметры показа фразы при известном отставании."""

    lag_ms: int
    level: str
    speed: float | None
    gap_ms: int
    compress: bool
    target_ratio: float | None

    def as_event(self, *, compressed: bool = False) -> dict:
        """Представление для события ``utterance`` / ``playback``."""
        return {
            "level": self.level,
            "lag_ms": self.lag_ms,
            "speed": self.speed,
            "gap_ms": self.gap_ms,
            "compress": self.compress,
            "target_ratio": self.target_ratio,
            "compressed": compressed,
        }


def lag_playback_policy(lag_ms: int | None) -> LagPlaybackPolicy:
    """Выбрать политику догона по последнему известному отставанию.

    ``None`` означает, что студент ещё не показывал ни одной фразы: работаем
    как на зелёном уровне. Отрицательное значение защищаемо приводим к нулю.
    """
    safe_lag = max(0, int(lag_ms or 0))
    level = lag_level(safe_lag)

    if level == "red":
        return LagPlaybackPolicy(
            lag_ms=safe_lag,
            level=level,
            speed=LAG_RED_SPEED,
            gap_ms=LAG_RED_GAP_MS,
            compress=True,
            target_ratio=LAG_RED_TARGET_RATIO,
        )
    if level == "yellow":
        return LagPlaybackPolicy(
            lag_ms=safe_lag,
            level=level,
            speed=LAG_YELLOW_SPEED,
            gap_ms=LAG_YELLOW_GAP_MS,
            compress=True,
            target_ratio=LAG_YELLOW_TARGET_RATIO,
        )
    return LagPlaybackPolicy(
        lag_ms=safe_lag,
        level="green",
        speed=None,
        gap_ms=LAG_GREEN_GAP_MS,
        compress=False,
        target_ratio=None,
    )


def should_compress(policy: LagPlaybackPolicy, text: str) -> bool:
    """Нужно ли сжимать текст: порог достигнут и фраза не слишком короткая."""
    return policy.compress and len((text or "").strip()) >= LAG_COMPRESS_MIN_CHARS
