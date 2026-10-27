/**
 * Тесты планировщика очереди клипов (C4).
 *
 * Планировщик — чистая функция над числами: на вход длительности клипов и
 * параметры, на выходе тайминги отрезков. Здесь проверяются правила ТЗ:
 * crossfade 150–250 мс, скорость 0.6–1.3x, пауза в нейтральной позе между
 * фразами и границы перекрытия коротких клипов.
 */

import { describe, expect, it } from "vitest";

import {
  DACTYL_CROSSFADE_MS,
  DEFAULT_CROSSFADE_MS,
  MAX_SPEED,
  MIN_SPEED,
  blendAt,
  clampCrossfade,
  clampSpeed,
  frameAt,
  planQueue,
  segmentAt,
  tailNeutralAt,
  toQueueClip,
  type QueueClip,
} from "./clip-queue";
import { decodeClipPayload } from "./clip";
import { buildClipFixture } from "./clip.fixture";
import { COUNTS, buildFace, buildHand, buildPose, flatten } from "./retarget.fixture";

/** Клип с заданной длительностью в секундах (при 30 FPS). */
function clip(durationSec: number, fps = 30): QueueClip {
  return { duration: durationSec, fps, frames: Math.round(durationSec * fps) };
}

describe("clampSpeed", () => {
  it("зажимает скорость в 0.6–1.3x", () => {
    expect(clampSpeed(1)).toBe(1);
    expect(clampSpeed(0.1)).toBe(MIN_SPEED);
    expect(clampSpeed(5)).toBe(MAX_SPEED);
    expect(clampSpeed(1.3)).toBe(1.3);
    expect(clampSpeed(0.6)).toBe(0.6);
  });

  it("нечисло трактует как 1x", () => {
    expect(clampSpeed(Number.NaN)).toBe(1);
    expect(clampSpeed(Infinity)).toBe(1);
  });
});

describe("clampCrossfade", () => {
  it("зажимает длину перехода в 150–250 мс", () => {
    expect(clampCrossfade(200)).toBe(200);
    expect(clampCrossfade(10)).toBe(150);
    expect(clampCrossfade(999)).toBe(250);
    expect(clampCrossfade(Number.NaN)).toBe(DEFAULT_CROSSFADE_MS);
  });
});

describe("planQueue", () => {
  it("раскладывает три клипа с перекрытием crossfade", () => {
    const plan = planQueue([clip(1), clip(1), clip(1)]);

    expect(plan.segments).toHaveLength(3);
    expect(plan.speed).toBe(1);
    expect(plan.crossfadeMs).toBe(DEFAULT_CROSSFADE_MS);

    const [a, b, c] = plan.segments;
    // Первый клип начинается с нуля, в него не входит переход.
    expect(a.startMs).toBe(0);
    expect(a.endMs).toBe(1000);
    expect(a.fadeInMs).toBe(0);
    expect(a.fadeOutMs).toBe(200);

    // Второй стартует за 200 мс до конца первого.
    expect(b.startMs).toBe(800);
    expect(b.endMs).toBe(1800);
    expect(b.fadeInMs).toBe(200);
    expect(b.fadeOutMs).toBe(200);

    // Последний уходит в нейтраль без перехода к следующему клипу.
    expect(c.startMs).toBe(1600);
    expect(c.endMs).toBe(2600);
    expect(c.fadeInMs).toBe(200);
    expect(c.fadeOutMs).toBe(0);

    // Итог меньше суммы длительностей из-за перекрытий.
    expect(plan.totalMs).toBe(2600);
    expect(plan.totalMs).toBeLessThan(3000);
  });

  it("единственный клип не имеет переходов", () => {
    const plan = planQueue([clip(1)]);
    expect(plan.segments).toHaveLength(1);
    expect(plan.segments[0].fadeInMs).toBe(0);
    expect(plan.segments[0].fadeOutMs).toBe(0);
    expect(plan.totalMs).toBe(1000);
  });

  it("пустая очередь даёт пустой план", () => {
    const plan = planQueue([]);
    expect(plan.segments).toEqual([]);
    expect(plan.totalMs).toBe(0);
  });

  it("скорость сокращает длительность клипов", () => {
    const plan = planQueue([clip(2)], { speed: 1.3 });
    expect(plan.speed).toBe(1.3);
    // 2 с / 1.3 ≈ 1538 мс.
    expect(plan.segments[0].durationMs).toBeCloseTo((2 / 1.3) * 1000, 3);
  });

  it("зажимает слишком большую и слишком малую скорость", () => {
    expect(planQueue([clip(1)], { speed: 10 }).speed).toBe(MAX_SPEED);
    expect(planQueue([clip(1)], { speed: 0.01 }).speed).toBe(MIN_SPEED);
  });

  it("зажимает длину crossfade в допустимый диапазон", () => {
    const short = planQueue([clip(2), clip(2)], { crossfadeMs: 20 });
    expect(short.crossfadeMs).toBe(150);

    const long = planQueue([clip(2), clip(2)], { crossfadeMs: 900 });
    expect(long.crossfadeMs).toBe(250);
  });

  it("ужимает crossfade для коротких клипов (дактиль)", () => {
    // Клип 0.2 с ≈ 200 мс; переход не больше половины клипа — 100 мс.
    const plan = planQueue([clip(0.2), clip(0.2)], { crossfadeMs: 200 });
    expect(plan.segments[1].fadeInMs).toBeCloseTo(100, 6);
    expect(plan.segments[0].fadeOutMs).toBeCloseTo(100, 6);
  });

  it("сохраняет порядок и индексы отрезков", () => {
    const plan = planQueue([clip(1), clip(1), clip(1), clip(1)]);
    expect(plan.segments.map((s) => s.index)).toEqual([0, 1, 2, 3]);
    // Каждый следующий начинается позже предыдущего.
    for (let i = 1; i < plan.segments.length; i += 1) {
      expect(plan.segments[i].startMs).toBeGreaterThan(plan.segments[i - 1].startMs);
    }
  });

  it("пауза между фразами добавляется к времени старта", () => {
    const plan = planQueue([clip(1), clip(1)], { gapMs: 500 });
    expect(plan.gapMs).toBe(500);
    // Второй клип начинается на 200 мс раньше конца первого плюс 500 мс паузы.
    expect(plan.segments[1].startMs).toBe(1000 - 200 + 500);
    expect(plan.totalMs).toBe(1000 - 200 + 500 + 1000);
  });

  it("использует frames/fps, если duration не задана", () => {
    const plan = planQueue([{ duration: 0, fps: 25, frames: 50 }]);
    expect(plan.segments[0].durationMs).toBeCloseTo(2000, 6);
  });

  it("поддерживает укороченный дактильный crossfade", () => {
    const plan = planQueue([clip(1), clip(1)], { crossfadeMs: DACTYL_CROSSFADE_MS });
    // DACTYL_CROSSFADE_MS (80) ниже минимума 150, планировщик зажимает его.
    expect(plan.crossfadeMs).toBe(150);
  });
});

describe("frameAt", () => {
  it("переводит время в номер кадра клипа", () => {
    const plan = planQueue([clip(1), clip(1)]);
    const second = plan.segments[1];
    const c = { frames: 30, fps: 30 };
    // Начало отрезка — нулевой кадр.
    expect(frameAt(second, c, second.startMs)).toBe(0);
    // Через 100 мс при 30 fps — третий кадр.
    expect(frameAt(second, c, second.startMs + 100)).toBe(3);
    // За концом — последний кадр.
    expect(frameAt(second, c, second.endMs + 1000)).toBe(29);
  });

  it("учитывает скорость отрезка", () => {
    const plan = planQueue([clip(1)], { speed: 1.3 });
    const segment = plan.segments[0];
    const c = { frames: 30, fps: 30 };
    // За 100 мс при 1.3x: 0.1 × 30 × 1.3 = 3.9 → кадр 3.
    expect(frameAt(segment, c, segment.startMs + 100)).toBe(3);
  });
});

describe("segmentAt", () => {
  it("находит отрезок по времени с учётом перекрытий", () => {
    const plan = planQueue([clip(1), clip(1)]);
    // Первый отрезок: 0–1000.
    expect(segmentAt(plan, 0)?.index).toBe(0);
    // В зоне перекрытия (800–1000) выигрывает более поздний — идём по порядку.
    expect(segmentAt(plan, 900)?.index).toBe(0);
    expect(segmentAt(plan, 1000)?.index).toBe(1);
  });

  it("после конца возвращает последний отрезок", () => {
    const plan = planQueue([clip(1), clip(1)]);
    expect(segmentAt(plan, plan.totalMs + 100)?.index).toBe(1);
  });

  it("на пустом плане возвращает null", () => {
    expect(segmentAt(planQueue([]), 0)).toBeNull();
  });
});

describe("blendAt", () => {
  it("в зоне входа растёт от 0 до 1", () => {
    const plan = planQueue([clip(1), clip(1)]);
    const second = plan.segments[1];
    expect(blendAt(plan, 1, second.startMs)).toBe(0);
    expect(blendAt(plan, 1, second.startMs + 100)).toBeCloseTo(0.5, 6);
    expect(blendAt(plan, 1, second.startMs + 200)).toBe(1);
    expect(blendAt(plan, 1, second.startMs + 500)).toBe(1);
  });

  it("для первого клипа всегда 1 (нет входа)", () => {
    const plan = planQueue([clip(1), clip(1)]);
    expect(blendAt(plan, 0, 0)).toBe(1);
  });
});

describe("tailNeutralAt", () => {
  it("в конце очереди плавно уводит в нейтраль", () => {
    const plan = planQueue([clip(1), clip(1)]);
    const last = plan.segments[1];
    expect(tailNeutralAt(plan, 1, last.endMs - 150)).toBe(0);
    expect(tailNeutralAt(plan, 1, last.endMs - 75)).toBeCloseTo(0.5, 6);
    expect(tailNeutralAt(plan, 1, last.endMs)).toBe(1);
  });

  it("для не-последнего отрезка всегда 0", () => {
    const plan = planQueue([clip(1), clip(1)]);
    expect(tailNeutralAt(plan, 0, 500)).toBe(0);
  });
});

describe("toQueueClip", () => {
  it("берёт длительность из кадров и fps", async () => {
    const values: number[] = [];
    for (let f = 0; f < 4; f += 1) {
      values.push(
        ...flatten(buildPose(0)),
        ...flatten(buildHand(1, "left")),
        ...flatten(buildHand(1, "right")),
        ...flatten(buildFace()),
      );
    }
    const fixture = buildClipFixture({
      frames: 4,
      fps: 20,
      layout: { pose: COUNTS.pose, hand_l: COUNTS.hand_l, hand_r: COUNTS.hand_r, face: COUNTS.face },
      values,
    });
    const decoded = await decodeClipPayload(fixture.payload);
    const described = toQueueClip(decoded);
    expect(described.frames).toBe(4);
    expect(described.fps).toBe(20);
    expect(described.duration).toBeCloseTo(0.2, 6);
  });
});
