/**
 * Тесты фильтра One Euro (C3).
 *
 * Проверяются свойства из статьи Casiez et al.: первый кадр проходит без
 * изменений, фильтр сглаживает шум, при быстром движении отставание меньше,
 * чем у обычного low-pass, `reset` обнуляет состояние.
 */

import { describe, expect, it } from "vitest";

import { OneEuroFilter, OneEuroLandmarks, OneEuroPoint } from "./one-euro";

describe("OneEuroFilter", () => {
  it("первое значение проходит без изменений", () => {
    const filter = new OneEuroFilter();
    expect(filter.filter(5)).toBe(5);
    expect(filter.last).toBe(5);
  });

  it("сглаживает постоянный шум вокруг среднего", () => {
    const filter = new OneEuroFilter({ minCutoff: 1, beta: 0 });
    const noisy = [0.5, 0.55, 0.45, 0.52, 0.48, 0.51, 0.49, 0.5];
    const out = noisy.map((v) => filter.filter(v));

    // Первое значение совпадает, дальше разброс выхода меньше разброса входа.
    expect(out[0]).toBe(0.5);
    const spread = (xs: number[]) => Math.max(...xs) - Math.min(...xs);
    expect(spread(out.slice(1))).toBeLessThan(spread(noisy));
  });

  it("отстаёт меньше при большой beta на быстром движении", () => {
    const slow = new OneEuroFilter({ minCutoff: 1, beta: 0 });
    const fast = new OneEuroFilter({ minCutoff: 1, beta: 1 });
    // Быстрый скачок: медленный фильтр далеко от цели, быстрый — ближе.
    slow.filter(0);
    fast.filter(0);
    let slowOut = 0;
    let fastOut = 0;
    for (let i = 0; i < 5; i += 1) {
      slowOut = slow.filter(1);
      fastOut = fast.filter(1);
    }
    expect(fastOut).toBeGreaterThan(slowOut);
  });

  it("сходится к постоянному значению", () => {
    const filter = new OneEuroFilter({ minCutoff: 1, beta: 0 });
    filter.filter(0);
    let out = 0;
    for (let i = 0; i < 60; i += 1) out = filter.filter(1);
    expect(out).toBeCloseTo(1, 2);
  });

  it("учитывает интервал между кадрами", () => {
    const filter = new OneEuroFilter({ minCutoff: 1, beta: 0 });
    filter.filter(0, 1 / 30);
    const out = filter.filter(1, 1 / 30);
    expect(out).toBeGreaterThan(0);
    expect(out).toBeLessThan(1);
  });

  it("reset возвращает фильтр в исходное состояние", () => {
    const filter = new OneEuroFilter();
    filter.filter(5);
    filter.filter(6);
    filter.reset();
    expect(filter.last).toBeNull();
    expect(filter.filter(1)).toBe(1);
  });
});

describe("OneEuroPoint", () => {
  it("фильтрует каждую компоненту отдельно", () => {
    const point = new OneEuroPoint({ minCutoff: 1, beta: 0 });
    point.filter({ x: 0, y: 0, z: 0 });
    const out = point.filter({ x: 1, y: 2, z: 3 });

    expect(out.x).toBeGreaterThan(0);
    expect(out.x).toBeLessThan(1);
    expect(out.y).toBeGreaterThan(0);
    expect(out.y).toBeLessThan(2);
    expect(out.z).toBeGreaterThan(0);
    expect(out.z).toBeLessThan(3);
  });

  it("сохраняет размерность (всегда три числа)", () => {
    const point = new OneEuroPoint();
    const out = point.filter({ x: 0.1, y: 0.2, z: 0.3 });
    expect(Object.keys(out).sort()).toEqual(["x", "y", "z"]);
  });
});

describe("OneEuroLandmarks", () => {
  it("держит по фильтру на точку и сохраняет длину кадра", () => {
    const landmarks = new OneEuroLandmarks({ minCutoff: 1, beta: 0 });
    const first = landmarks.filter([
      { x: 0, y: 0, z: 0 },
      { x: 0, y: 0, z: 0 },
    ]);
    const second = landmarks.filter([
      { x: 1, y: 1, z: 1 },
      { x: 1, y: 1, z: 1 },
    ]);

    expect(first).toHaveLength(2);
    expect(second).toHaveLength(2);
    // Вторая точка фильтруется своим экземпляром: значение сглажено, не 1.
    expect(second[0].x).toBeCloseTo(second[1].x, 10);
    expect(second[0].x).toBeLessThan(1);
  });

  it("reset обнуляет все точки", () => {
    const landmarks = new OneEuroLandmarks();
    landmarks.filter([{ x: 1, y: 1, z: 1 }]);
    landmarks.reset();
    const out = landmarks.filter([{ x: 4, y: 4, z: 4 }]);
    expect(out[0]).toEqual({ x: 4, y: 4, z: 4 });
  });
});
