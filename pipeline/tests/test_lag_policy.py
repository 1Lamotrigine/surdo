"""F8: логика порогов FR-15/FR-16 без БД и очереди."""

from __future__ import annotations

import pytest

from pipeline.lag_policy import (
    LAG_COMPRESS_MIN_CHARS,
    LAG_GREEN_GAP_MS,
    LAG_RED_GAP_MS,
    LAG_RED_SPEED,
    LAG_RED_TARGET_RATIO,
    LAG_YELLOW_GAP_MS,
    LAG_YELLOW_SPEED,
    LAG_YELLOW_TARGET_RATIO,
    lag_playback_policy,
    should_compress,
)


@pytest.mark.parametrize(
    ("lag_ms", "level", "speed", "gap_ms", "compress", "ratio"),
    [
        (0, "green", None, LAG_GREEN_GAP_MS, False, None),
        (5_000, "green", None, LAG_GREEN_GAP_MS, False, None),
        (5_001, "yellow", LAG_YELLOW_SPEED, LAG_YELLOW_GAP_MS, True, LAG_YELLOW_TARGET_RATIO),
        (10_000, "yellow", LAG_YELLOW_SPEED, LAG_YELLOW_GAP_MS, True, LAG_YELLOW_TARGET_RATIO),
        (10_001, "red", LAG_RED_SPEED, LAG_RED_GAP_MS, True, LAG_RED_TARGET_RATIO),
    ],
)
def test_lag_playback_policy_thresholds(
    lag_ms, level, speed, gap_ms, compress, ratio
):
    """FR-16: выше 5 с ускоряем/сжимаем, выше 10 с — максимум и без пауз."""
    policy = lag_playback_policy(lag_ms)

    assert policy.lag_ms == lag_ms
    assert policy.level == level
    assert policy.speed == speed
    assert policy.gap_ms == gap_ms
    assert policy.compress is compress
    assert policy.target_ratio == ratio


def test_missing_lag_keeps_normal_playback():
    policy = lag_playback_policy(None)

    assert policy.level == "green"
    assert policy.lag_ms == 0
    assert policy.speed is None
    assert policy.compress is False


def test_negative_lag_is_treated_as_zero():
    assert lag_playback_policy(-500).level == "green"


def test_policy_event_contains_playback_fields():
    event = lag_playback_policy(11_000).as_event(compressed=True)

    assert event == {
        "level": "red",
        "lag_ms": 11_000,
        "speed": LAG_RED_SPEED,
        "gap_ms": 0,
        "compress": True,
        "target_ratio": LAG_RED_TARGET_RATIO,
        "compressed": True,
    }


def test_short_phrase_is_not_compressed():
    policy = lag_playback_policy(11_000)
    short = "Учебник"
    long = "а" * LAG_COMPRESS_MIN_CHARS

    assert should_compress(policy, short) is False
    assert should_compress(policy, long) is True


def test_green_policy_never_compresses():
    assert should_compress(lag_playback_policy(1_000), "а" * 200) is False
