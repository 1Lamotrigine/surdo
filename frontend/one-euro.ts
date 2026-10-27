/**
 * Фильтр One Euro (C3) — сглаживание landmark'ов, убирает дрожь пальцев
 * (``docs/spec/clip-format.md``, 5.4). Алгоритм: Casiez, Roussel, Vogel
 * «1€ Filter: A Simple Speed-based Low-pass Filter for Noisy Input in
 * Interactive Systems» (CHI 2012).
 *
 * Модуль без зависимостей: применяется и к скалярам, и к вектору точки
 * (`{x, y, z}`). Настраивается тремя параметрами:
 * - `minCutoff` — частота среза в покое (меньше — сильнее сглаживание);
 * - `beta` — реакция на скорость (больше — меньше отставание при быстром жесте);
 * - `derivateCutoff` — срез производной (обычно 1.0).
 *
 * Фильтр stateful: одна точка — один экземпляр. Для landmarks удобно держать
 * `OneEuroPointFilter` (по экземпляру на точку) или `OneEuroLandmarkFilter`
 * (сетка точек на кадр).
 */

export type OneEuroOptions = {
  minCutoff?: number;
  beta?: number;
  derivateCutoff?: number;
  /** Частота дискретизации по умолчанию, Гц (клипы пишутся на 30 FPS). */
  frequency?: number;
};

const DEFAULT_MIN_CUTOFF = 1.0;
const DEFAULT_BETA = 0.007;
const DEFAULT_DERIVATE_CUTOFF = 1.0;
const DEFAULT_FREQUENCY = 30;

/** Коэффициент сглаживания `alpha` из частоты среза и интервала. */
function smoothingFactor(cutoff: number, deltaSeconds: number): number {
  const tau = 1 / (2 * Math.PI * cutoff);
  return 1 / (1 + tau / deltaSeconds);
}

/** Одномерный фильтр One Euro. */
export class OneEuroFilter {
  private readonly frequency: number;
  private minCutoff: number;
  private beta: number;
  private readonly derivateCutoff: number;

  private xPrev: number | null = null;
  private dxPrev = 0;

  constructor(options: OneEuroOptions = {}) {
    this.frequency = options.frequency ?? DEFAULT_FREQUENCY;
    this.minCutoff = options.minCutoff ?? DEFAULT_MIN_CUTOFF;
    this.beta = options.beta ?? DEFAULT_BETA;
    this.derivateCutoff = options.derivateCutoff ?? DEFAULT_DERIVATE_CUTOFF;
  }

  /**
   * Отфильтровать очередное значение.
   * @param value входное значение
   * @param deltaSeconds интервал между кадрами (по умолчанию 1/`frequency`)
   */
  filter(value: number, deltaSeconds?: number): number {
    const delta = deltaSeconds && deltaSeconds > 0 ? deltaSeconds : 1 / this.frequency;

    if (this.xPrev === null) {
      // Первый кадр: фильтр нечего сглаживать, начинаем с исходного значения.
      this.xPrev = value;
      this.dxPrev = 0;
      return value;
    }

    // Оценка производной (скорости) и её сглаживание.
    const dx = (value - this.xPrev) / delta;
    const alphaD = smoothingFactor(this.derivateCutoff, delta);
    const dxHat = alphaD * dx + (1 - alphaD) * this.dxPrev;

    // Частота среза растёт со скоростью: быстрое движение меньше фильтруется.
    const cutoff = this.minCutoff + this.beta * Math.abs(dxHat);
    const alpha = smoothingFactor(cutoff, delta);
    const xHat = alpha * value + (1 - alpha) * this.xPrev;

    this.xPrev = xHat;
    this.dxPrev = dxHat;
    return xHat;
  }

  /** Сбросить состояние (например, при обрыве непрерывности). */
  reset(): void {
    this.xPrev = null;
    this.dxPrev = 0;
  }

  /** Последнее отфильтрованное значение или `null`, если фильтр ещё не работал. */
  get last(): number | null {
    return this.xPrev;
  }
}

export type Vec3 = { x: number; y: number; z: number };

/** Фильтр одной 3D-точки: три независимых `OneEuroFilter`. */
export class OneEuroPoint {
  private readonly fx: OneEuroFilter;
  private readonly fy: OneEuroFilter;
  private readonly fz: OneEuroFilter;

  constructor(options: OneEuroOptions = {}) {
    this.fx = new OneEuroFilter(options);
    this.fy = new OneEuroFilter(options);
    this.fz = new OneEuroFilter(options);
  }

  filter(point: Vec3, deltaSeconds?: number): Vec3 {
    return {
      x: this.fx.filter(point.x, deltaSeconds),
      y: this.fy.filter(point.y, deltaSeconds),
      z: this.fz.filter(point.z, deltaSeconds),
    };
  }

  reset(): void {
    this.fx.reset();
    this.fy.reset();
    this.fz.reset();
  }
}

/**
 * Фильтр набора точек: держит по одному `OneEuroPoint` на индекс.
 * Число точек фиксировано (layout клипа), поэтому набор растёт только при
 * первом кадре и дальше не пересоздаётся.
 */
export class OneEuroLandmarks {
  private readonly points: OneEuroPoint[] = [];
  private readonly options: OneEuroOptions;

  constructor(options: OneEuroOptions = {}) {
    this.options = options;
  }

  /** Отфильтровать массив точек (обычно все точки кадра). */
  filter(points: Vec3[], deltaSeconds?: number): Vec3[] {
    return points.map((point, index) => {
      if (!this.points[index]) {
        this.points[index] = new OneEuroPoint(this.options);
      }
      return this.points[index].filter(point, deltaSeconds);
    });
  }

  reset(): void {
    for (const point of this.points) point.reset();
  }
}
