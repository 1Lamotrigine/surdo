/**
 * Фикстура landmarks в формате MediaPipe Holistic для тестов ретаргета (C3).
 *
 * Собирает синтетический скелет (поза 33, кисти 21, лицо 468) с известными
 * координатами, чтобы Kalidokit считал осмысленные углы. Нормализация как у
 * MediaPipe: диапазон 0..1, `y` направлена вниз.
 */

export type Point = { x: number; y: number; z: number };

export type SkeletonSpec = {
  /** Доля поднятия правой кисти: 0 — рука внизу, 1 — поднята вверх. */
  rightArmRaise?: number;
  /** Разведение пальцев правой кисти: 0 — кулак, 1 — раскрытая ладонь. */
  rightHandSpread?: number;
};

const POSE_COUNT = 33;
const HAND_COUNT = 21;
const FACE_COUNT = 468;

/** Нейтральная стойка: руки опущены по швам, центр кадра. */
const POSE_BASE: Point[] = Array.from({ length: POSE_COUNT }, () => ({ x: 0.5, y: 0.5, z: 0 }));

function setPoint(points: Point[], index: number, x: number, y: number, z = 0): void {
  points[index] = { x, y, z };
}

/** Собрать позу (33 точки) с поднятой правой рукой при `raise` ∈ [0, 1]. */
export function buildPose(raise = 0): Point[] {
  const lm = POSE_BASE.map((p) => ({ ...p }));

  setPoint(lm, 0, 0.5, 0.2); // нос
  setPoint(lm, 11, 0.42, 0.3); // правое плечо
  setPoint(lm, 12, 0.58, 0.3); // левое плечо
  // Правая рука: локоть на полпути, кисть поднимается с `raise`.
  setPoint(lm, 13, 0.4, 0.45 - raise * 0.2); // правый локоть
  setPoint(lm, 15, 0.4, 0.6 - raise * 0.5); // правая кисть
  setPoint(lm, 14, 0.6, 0.45); // левый локоть
  setPoint(lm, 16, 0.6, 0.6); // левая кисть
  setPoint(lm, 17, 0.4, 0.62); // правый мизинец (для calcArms)
  setPoint(lm, 19, 0.4, 0.64);
  setPoint(lm, 18, 0.6, 0.62);
  setPoint(lm, 20, 0.6, 0.64);
  setPoint(lm, 23, 0.44, 0.7); // правое бедро
  setPoint(lm, 24, 0.56, 0.7); // левое бедро
  setPoint(lm, 25, 0.44, 0.85);
  setPoint(lm, 26, 0.56, 0.85);

  for (const point of lm) point.z = 0;
  return lm;
}

/**
 * Собрать кисть (21 точка). `spread` = 0 — кулак (пальцы прижаты к ладони),
 * `spread` = 1 — раскрытая ладонь (пальцы вытянуты).
 */
export function buildHand(spread = 1, side: "left" | "right" = "right"): Point[] {
  const sign = side === "right" ? 1 : -1;
  const lm: Point[] = Array.from({ length: HAND_COUNT }, () => ({ x: 0.5, y: 0.5, z: 0 }));

  // Запястье.
  setPoint(lm, 0, 0.5, 0.55);
  // Пальцы: MCP → PIP → DIP → TIP. MCP на линии костяшек (y=0.45), кончики
  // уходят вверх при раскрытой ладони и заворачиваются назад при кулаке.
  const fingers: [number, number, number, number, number][] = [
    [1, 2, 3, 4, 0.06], // большой: в стороне
    [5, 6, 7, 8, 0.02],
    [9, 10, 11, 12, 0.0],
    [13, 14, 15, 16, -0.02],
    [17, 18, 19, 20, -0.04],
  ];
  for (const [mcp, pip, dip, tip, offset] of fingers) {
    const x = 0.5 + sign * offset;
    // Костяшка.
    setPoint(lm, mcp, x, 0.45);
    if (spread >= 0.5) {
      // Раскрытая ладонь: палец — прямая линия вверх (шарниры не согнуты).
      setPoint(lm, pip, x, 0.40);
      setPoint(lm, dip, x, 0.37);
      setPoint(lm, tip, x, 0.35);
    } else {
      // Кулак: палец заворачивается дугой, кончик уходит вниз-в сторону.
      setPoint(lm, pip, x, 0.40);
      setPoint(lm, dip, x + 0.03, 0.38);
      setPoint(lm, tip, x + 0.02, 0.43);
    }
  }
  return lm;
}

/** Собрать лицо (468 точек): контур и внутренние точки для calcHead. */
export function buildFace(centerX = 0.5, centerY = 0.25): Point[] {
  const lm: Point[] = Array.from({ length: FACE_COUNT }, () => ({ x: centerX, y: centerY, z: 0 }));

  // Точки, которые читают calcHead и calcMouth.
  setPoint(lm, 21, centerX - 0.06, centerY - 0.06); // левый верх
  setPoint(lm, 251, centerX + 0.06, centerY - 0.06); // правый верх
  setPoint(lm, 397, centerX + 0.06, centerY + 0.06); // правый низ
  setPoint(lm, 172, centerX - 0.06, centerY + 0.06); // левый низ
  setPoint(lm, 13, centerX, centerY + 0.03);
  setPoint(lm, 14, centerX, centerY + 0.05);
  setPoint(lm, 61, centerX - 0.03, centerY + 0.04);
  setPoint(lm, 291, centerX + 0.03, centerY + 0.04);
  setPoint(lm, 133, centerX - 0.02, centerY);
  setPoint(lm, 362, centerX + 0.02, centerY);
  setPoint(lm, 130, centerX - 0.04, centerY);
  setPoint(lm, 263, centerX + 0.04, centerY);
  return lm;
}

/** Плоский массив точек → числа для `values` фикстуры клипа. */
export function flatten(points: Point[]): number[] {
  const values: number[] = [];
  for (const point of points) values.push(point.x, point.y, point.z);
  return values;
}

export const COUNTS = { pose: POSE_COUNT, hand_l: HAND_COUNT, hand_r: HAND_COUNT, face: FACE_COUNT };
