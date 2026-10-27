/**
 * F8: клиентская часть политики догона (FR-16).
 *
 * Сервер присылает скорость и паузу; клиент не пересчитывает пороги, а только
 * безопасно нормализует числа и совмещает их с ручной скоростью студента C7.
 */

import { describe, expect, it } from "vitest";

import { MAX_SPEED, MIN_SPEED } from "./clip-queue";
import {
  DEFAULT_PLAYBACK_POLICY,
  effectivePlaybackSpeed,
  normalizePlaybackPolicy,
  playbackGapMs,
} from "./lag-policy";

describe("normalizePlaybackPolicy", () => {
  it("без события даёт обычный показ", () => {
    expect(normalizePlaybackPolicy(undefined)).toEqual(DEFAULT_PLAYBACK_POLICY);
  });

  it("читает скорость, паузу и уровень из события", () => {
    const policy = normalizePlaybackPolicy({
      level: "red",
      lag_ms: 12_000,
      speed: 1.3,
      gap_ms: 0,
      compressed: true,
    });

    expect(policy.level).toBe("red");
    expect(policy.lagMs).toBe(12_000);
    expect(policy.speed).toBe(1.3);
    expect(policy.gapMs).toBe(0);
    expect(policy.compressed).toBe(true);
  });

  it("не доверяет нечислам и отрицательным задержкам", () => {
    const policy = normalizePlaybackPolicy({
      level: "unknown",
      lag_ms: -5,
      speed: Number.POSITIVE_INFINITY,
      gap_ms: -20,
    });

    expect(policy.level).toBe("green");
    expect(policy.lagMs).toBe(0);
    expect(policy.speed).toBeNull();
    expect(policy.gapMs).toBe(0);
  });

  it("зажимает скорость в 0.6–1.3x", () => {
    expect(normalizePlaybackPolicy({ speed: 0.1 }).speed).toBe(MIN_SPEED);
    expect(normalizePlaybackPolicy({ speed: 9 }).speed).toBe(MAX_SPEED);
  });
});

describe("effectivePlaybackSpeed", () => {
  it("на зелёном уровне сохраняет ручную скорость студента", () => {
    const slow = normalizePlaybackPolicy({ level: "green", speed: null });
    const fast = normalizePlaybackPolicy({ level: "green", speed: null });

    expect(effectivePlaybackSpeed(0.6, slow)).toBe(0.6);
    expect(effectivePlaybackSpeed(1.2, fast)).toBe(1.2);
  });

  it("на жёлтом берёт максимум из ручной и скорости догона", () => {
    const policy = normalizePlaybackPolicy({ level: "yellow", speed: 1.15 });

    expect(effectivePlaybackSpeed(0.8, policy)).toBe(1.15);
    expect(effectivePlaybackSpeed(1.2, policy)).toBe(1.2);
  });

  it("на красном не превышает 1.3x", () => {
    const policy = normalizePlaybackPolicy({ level: "red", speed: 1.3 });

    expect(effectivePlaybackSpeed(0.6, policy)).toBe(1.3);
    expect(effectivePlaybackSpeed(2, policy)).toBe(MAX_SPEED);
  });
});

describe("playbackGapMs", () => {
  it("на красном пропускает паузы", () => {
    const policy = normalizePlaybackPolicy({ level: "red", gap_ms: 0 });
    expect(playbackGapMs(policy)).toBe(0);
  });

  it("не пропускает отрицательную паузу", () => {
    expect(playbackGapMs(normalizePlaybackPolicy({ gap_ms: -100 }))).toBe(0);
  });
});
