/**
 * Предпросмотр скелета MediaPipe Holistic (D1).
 *
 * MediaPipe отдаёт landmarks в нормализованных координатах кадра: `0…1` по
 * ширине и высоте, `z` — относительная глубина. Этот модуль переводит их в
 * пиксели холста с учётом `object-fit: cover` и зеркального отображения камеры,
 * собирает отрезки скелета и рисует их. Вся геометрия — чистые функции, поэтому
 * проверяется в vitest без камеры и DOM.
 */

export type Landmark = {
  x: number;
  y: number;
  z: number;
  /** Достоверность точки позы; у кистей и лица может отсутствовать. */
  visibility?: number;
};

/** Кадр Holistic: поза (33), лицо (468) и обе кисти (по 21). */
export type HolisticFrame = {
  pose: Landmark[];
  face: Landmark[];
  leftHand: Landmark[];
  rightHand: Landmark[];
};

export type SkeletonGroup = "pose" | "hand" | "face";

export type Connection = readonly [start: number, end: number];

/** Связи скелета позы MediaPipe (33 точки). */
export const POSE_CONNECTIONS: readonly Connection[] = [
  [0, 1], [1, 2], [2, 3], [3, 7],
  [0, 4], [4, 5], [5, 6], [6, 8],
  [9, 10],
  [11, 12], [11, 13], [13, 15], [15, 17], [15, 19], [15, 21], [17, 19],
  [12, 14], [14, 16], [16, 18], [16, 20], [16, 22], [18, 20],
  [11, 23], [12, 24], [23, 24], [23, 25], [24, 26],
  [25, 27], [26, 28], [27, 29], [28, 30], [29, 31], [30, 32],
  [27, 31], [28, 32],
];

/** Связи кисти MediaPipe (21 точка, одинакова для левой и правой). */
export const HAND_CONNECTIONS: readonly Connection[] = [
  [0, 1], [1, 2], [2, 3], [3, 4],
  [0, 5], [5, 6], [6, 7], [7, 8],
  [5, 9], [9, 10], [10, 11], [11, 12],
  [9, 13], [13, 14], [14, 15], [15, 16],
  [13, 17], [0, 17], [17, 18], [18, 19], [19, 20],
];

/** Овал лица: достаточно, чтобы видеть наклон и мимику без 468 рёбер. */
export const FACE_CONNECTIONS: readonly Connection[] = [
  [10, 338], [338, 297], [297, 332], [332, 284], [284, 251], [251, 389],
  [389, 356], [356, 454], [454, 323], [323, 361], [361, 288], [288, 397],
  [397, 365], [365, 379], [379, 378], [378, 400], [400, 377], [377, 152],
  [152, 148], [148, 176], [176, 149], [149, 150], [150, 136], [136, 172],
  [172, 58], [58, 132], [132, 93], [93, 234], [234, 127], [127, 162],
  [162, 21], [21, 54], [54, 103], [103, 67], [67, 109], [109, 10],
  // Глаза.
  [263, 249], [249, 390], [390, 373], [373, 374], [374, 380], [380, 381],
  [381, 382], [382, 362], [263, 466], [466, 388], [388, 387], [387, 386],
  [386, 385], [385, 384], [384, 398], [398, 362],
  [33, 7], [7, 163], [163, 144], [144, 145], [145, 153], [153, 154],
  [154, 155], [155, 133], [33, 246], [246, 161], [161, 160], [160, 159],
  [159, 158], [158, 157], [157, 173], [173, 133],
  // Брови.
  [276, 283], [283, 282], [282, 295], [295, 285], [300, 293], [293, 334],
  [334, 296], [296, 336],
  [46, 53], [53, 52], [52, 65], [65, 55], [70, 63], [63, 105], [105, 66],
  [66, 107],
  // Губы: внешний и внутренний контур.
  [61, 146], [146, 91], [91, 181], [181, 84], [84, 17], [17, 314],
  [314, 405], [405, 321], [321, 375], [375, 291], [61, 185], [185, 40],
  [40, 39], [39, 37], [37, 0], [0, 267], [267, 269], [269, 270], [270, 409],
  [409, 291], [78, 95], [95, 88], [88, 178], [178, 87], [87, 14], [14, 317],
  [317, 402], [402, 318], [318, 324], [324, 308], [78, 191], [191, 80],
  [80, 81], [81, 82], [82, 13], [13, 312], [312, 311], [311, 310], [310, 415],
  [415, 308],
];

/** Как кадр камеры вписан в холст (`object-fit: cover`). */
export type Viewport = {
  width: number;
  height: number;
  videoWidth: number;
  videoHeight: number;
  /** Камера смотрит на человека как в зеркало: x отражается. */
  mirror?: boolean;
};

export type Segment = {
  group: SkeletonGroup;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
};

export type SegmentOptions = {
  groups?: readonly SkeletonGroup[];
  /**
   * Минимальная видимость точки позы. Точки лица и кистей MediaPipe часто не
   * отдают `visibility`, поэтому фильтр применяется только к заданным значениям.
   */
  minVisibility?: number;
};

/** Масштаб и сдвиг кадра камеры внутри холста при `object-fit: cover`. */
export function coverTransform(viewport: Viewport): {
  scale: number;
  offsetX: number;
  offsetY: number;
} {
  const videoWidth = Math.max(1, viewport.videoWidth);
  const videoHeight = Math.max(1, viewport.videoHeight);
  const scale = Math.max(viewport.width / videoWidth, viewport.height / videoHeight);
  return {
    scale,
    offsetX: (viewport.width - videoWidth * scale) / 2,
    offsetY: (viewport.height - videoHeight * scale) / 2,
  };
}

/** Нормализованная точка → пиксели холста. */
export function mapLandmark(
  landmark: Landmark,
  viewport: Viewport,
): { x: number; y: number } {
  const { scale, offsetX, offsetY } = coverTransform(viewport);
  const x = viewport.mirror ? 1 - landmark.x : landmark.x;
  return {
    x: offsetX + x * viewport.videoWidth * scale,
    y: offsetY + landmark.y * viewport.videoHeight * scale,
  };
}

function connectionsFor(frame: HolisticFrame, group: SkeletonGroup): {
  landmarks: Landmark[];
  connections: readonly Connection[];
}[] {
  if (group === "pose") {
    return [{ landmarks: frame.pose, connections: POSE_CONNECTIONS }];
  }
  if (group === "face") {
    return [{ landmarks: frame.face, connections: FACE_CONNECTIONS }];
  }
  return [
    { landmarks: frame.leftHand, connections: HAND_CONNECTIONS },
    { landmarks: frame.rightHand, connections: HAND_CONNECTIONS },
  ];
}

/**
 * Отрезки скелета в пикселях холста. Недостающие точки и точки ниже порога
 * видимости пропускаются — так скелет не «прыгает» на края кадра.
 */
export function skeletonSegments(
  frame: HolisticFrame,
  viewport: Viewport,
  options: SegmentOptions = {},
): Segment[] {
  const groups = options.groups ?? (["pose", "hand", "face"] as const);
  const minVisibility = options.minVisibility ?? 0.5;
  const segments: Segment[] = [];

  for (const group of groups) {
    for (const { landmarks, connections } of connectionsFor(frame, group)) {
      for (const [start, end] of connections) {
        const a = landmarks[start];
        const b = landmarks[end];
        if (!a || !b) continue;
        if ((a.visibility ?? 1) < minVisibility || (b.visibility ?? 1) < minVisibility) {
          continue;
        }
        const from = mapLandmark(a, viewport);
        const to = mapLandmark(b, viewport);
        segments.push({ group, x1: from.x, y1: from.y, x2: to.x, y2: to.y });
      }
    }
  }

  return segments;
}

export const SKELETON_COLORS: Record<SkeletonGroup, string> = {
  pose: "#fbbf24",
  hand: "#38bdf8",
  face: "#86efac",
};

/** Нарисовать скелет поверх видео. */
export function drawSkeleton(
  context: CanvasRenderingContext2D,
  frame: HolisticFrame,
  viewport: Viewport,
  options: SegmentOptions = {},
): void {
  const segments = skeletonSegments(frame, viewport, options);
  context.save();
  context.lineCap = "round";
  context.lineJoin = "round";

  for (const group of ["face", "pose", "hand"] as const) {
    const groupSegments = segments.filter((segment) => segment.group === group);
    if (groupSegments.length === 0) continue;
    context.strokeStyle = SKELETON_COLORS[group];
    context.lineWidth = group === "hand" ? 3 : group === "pose" ? 4 : 1.5;
    context.globalAlpha = group === "face" ? 0.7 : 1;
    context.beginPath();
    for (const segment of groupSegments) {
      context.moveTo(segment.x1, segment.y1);
      context.lineTo(segment.x2, segment.y2);
    }
    context.stroke();
  }

  context.restore();
}
