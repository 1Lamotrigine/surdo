/**
 * Тесты плеера анимаций (H1): длина crossfade и границы скорости.
 *
 * Сам `AnimationMixer` требует WebGL/сцены, поэтому проверяется чистая логика
 * таймингов; показ анимаций в браузере проверяется вручную на странице /avatar/.
 */

import { describe, expect, it } from "vitest";

import { animationCrossfadeMs } from "./animation-player";
import { DEFAULT_CROSSFADE_MS, MAX_CROSSFADE_MS, MIN_CROSSFADE_MS } from "./clip-queue";

describe("animationCrossfadeMs", () => {
  it("по умолчанию берёт стандартную длину перехода", () => {
    expect(animationCrossfadeMs(undefined, 2000)).toBe(DEFAULT_CROSSFADE_MS);
  });

  it("зажимает переход в 150–250 мс", () => {
    expect(animationCrossfadeMs(10, 5000)).toBe(MIN_CROSSFADE_MS);
    expect(animationCrossfadeMs(900, 5000)).toBe(MAX_CROSSFADE_MS);
  });

  it("не съедает короткий клип: не больше половины длительности", () => {
    expect(animationCrossfadeMs(200, 300)).toBe(150);
    expect(animationCrossfadeMs(200, 200)).toBe(100);
  });

  it("игнорирует неизвестную длительность", () => {
    expect(animationCrossfadeMs(200, 0)).toBe(200);
    expect(animationCrossfadeMs(200, Number.NaN)).toBe(200);
  });
});
