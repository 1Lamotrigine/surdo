/**
 * Политика догона отставания на клиенте (F8, FR-16).
 *
 * Сервер присылает её в событии `utterance` (для следующей фразы) и в событии
 * `playback` после `display_started` (для уже играющей). Здесь только
 * нормализация чисел и совмещение с ручной скоростью студента C7:
 *
 * - `speed = null` (зелёный уровень) не трогает ручную скорость 0.6–1.2x;
 * - на жёлтом/красном берётся максимум из ручной и скорости догона, но не
 *   выше 1.3x, чтобы догон не замедлял уже выбранный студентом темп;
 * - `gap_ms` — пауза между клипами; на красном уровне сервер присылает 0.
 */

import { MAX_SPEED, MIN_SPEED, clamp, clampSpeed } from "./clip-queue";

/** Сырые параметры догона из события WebSocket. */
export type PlaybackPolicy = {
  level?: string;
  lag_ms?: number;
  speed?: number | null;
  gap_ms?: number;
  compress?: boolean;
  target_ratio?: number | null;
  compressed?: boolean;
};

/** Нормализованная политика, с которой работает плеер. */
export type NormalizedPlaybackPolicy = {
  level: "green" | "yellow" | "red";
  lagMs: number;
  /** `null` — сохранить ручную скорость студента. */
  speed: number | null;
  gapMs: number;
  compressed: boolean;
};

/** Политика по умолчанию: обычная скорость без дополнительной паузы. */
export const DEFAULT_PLAYBACK_POLICY: NormalizedPlaybackPolicy = {
  level: "green",
  lagMs: 0,
  speed: null,
  gapMs: 0,
  compressed: false,
};

function normalizedLevel(level: unknown): NormalizedPlaybackPolicy["level"] {
  return level === "yellow" || level === "red" ? level : "green";
}

/** Привести событие сервера к безопасным числам, не доверяя клиентскому вводу. */
export function normalizePlaybackPolicy(
  raw: PlaybackPolicy | null | undefined,
): NormalizedPlaybackPolicy {
  if (!raw || typeof raw !== "object") return { ...DEFAULT_PLAYBACK_POLICY };

  const lagMs =
    typeof raw.lag_ms === "number" && Number.isFinite(raw.lag_ms)
      ? Math.max(0, Math.round(raw.lag_ms))
      : 0;
  const speed =
    typeof raw.speed === "number" && Number.isFinite(raw.speed)
      ? clampSpeed(raw.speed)
      : null;
  const gapMs =
    typeof raw.gap_ms === "number" && Number.isFinite(raw.gap_ms)
      ? Math.max(0, Math.round(raw.gap_ms))
      : 0;

  return {
    level: normalizedLevel(raw.level),
    lagMs,
    speed,
    gapMs,
    compressed: raw.compressed === true,
  };
}

/** Итоговая скорость: ручная настройка, но не ниже скорости догона. */
export function effectivePlaybackSpeed(
  baseSpeed: number,
  policy: NormalizedPlaybackPolicy,
): number {
  const base = clampSpeed(baseSpeed);
  if (policy.speed === null) return base;
  return clamp(Math.max(base, clampSpeed(policy.speed)), MIN_SPEED, MAX_SPEED);
}

/** Пауза между клипами из политики; отрицательные значения невозможны. */
export function playbackGapMs(policy: NormalizedPlaybackPolicy): number {
  return Math.max(0, policy.gapMs);
}
