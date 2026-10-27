/**
 * Запись клипа жеста (D2): кадры Holistic → обрезка → 30 FPS → One Euro →
 * формат клипа (C2).
 *
 * Камера отдаёт кадры с переменной частотой, а клип должен быть равномерным:
 * после обрезки кадры пересэмплируются на `fps` (по умолчанию 30), недостающие
 * части скелета заполняются предыдущим кадром, затем landmarks сглаживаются
 * фильтром One Euro и упаковываются в `.json.gz`.
 *
 * Модуль не трогает DOM: страница записи передаёт сюда массив кадров с
 * метками времени, а обратно получает payload и готовый файл.
 */

import type { ClipLayout } from "./clip";
import {
  encodeClipPayload,
  packClipFile,
  type ClipPayload,
} from "./clip-encode";
import { OneEuroLandmarks, type OneEuroOptions, type Vec3 } from "./one-euro";
import type { HolisticFrame, Landmark } from "./skeleton";

/** Единый layout клипа: как у MediaPipe Holistic и демо-клипов C3. */
export const RECORD_LAYOUT: ClipLayout = {
  pose: 33,
  hand_l: 21,
  hand_r: 21,
  face: 468,
};

export const RECORD_TOTAL_POINTS = Object.values(RECORD_LAYOUT).reduce(
  (sum, count) => sum + count,
  0,
);
export const RECORD_FPS = 30;
export const RECORD_MAX_FRAMES = 300;

/** Кадр с камеры и его метка времени (`performance.now`, мс). */
export type CapturedFrame = {
  timeMs: number;
  frame: HolisticFrame;
};

/** Диапазон кадров записи: `start` включительно, `end` не включается. */
export type TrimRange = {
  start: number;
  end: number;
};

export type AutoTrimOptions = {
  /** Сколько кадров оставить до/после движения (по умолчанию — без запаса). */
  paddingFrames?: number;
  minFrames?: number;
};

export type PrepareOptions = {
  smooth?: boolean;
  smoothing?: OneEuroOptions;
};

export type EncodeRecordedClipOptions = {
  frames: CapturedFrame[];
  range: TrimRange;
  fps?: number;
  maxFrames?: number;
  gloss?: string;
  smooth?: boolean;
  smoothing?: OneEuroOptions;
};

export type EncodedRecordedClip = {
  payload: ClipPayload;
  /** Содержимое `.json.gz`: то, что скачивает редактор. */
  file: Uint8Array;
  frameCount: number;
  durationMs: number;
};

export class ClipRecordError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ClipRecordError";
  }
}

function point(x = 0.5, y = 0.5, z = 0): Landmark {
  return { x, y, z };
}

function clonePoint(value: Landmark): Landmark {
  const copy: Landmark = { x: value.x, y: value.y, z: value.z };
  if (value.visibility !== undefined) copy.visibility = value.visibility;
  return copy;
}

function emptyFrame(): HolisticFrame {
  return { pose: [], face: [], leftHand: [], rightHand: [] };
}

/** Порог видимости точек позы — тот же, что у предпросмотра скелета (D1). */
const POSE_VISIBILITY = 0.3;

/** Есть ли в кадре тело или хотя бы одна кисть (лицо само по себе не жест). */
export function frameHasBody(frame: HolisticFrame): boolean {
  const visiblePose = frame.pose.filter(
    (point) => (point.visibility ?? 1) >= POSE_VISIBILITY,
  ).length;
  return (
    visiblePose >= 15 ||
    frame.leftHand.length >= 21 ||
    frame.rightHand.length >= 21
  );
}

/**
 * Автоматическая обрезка начала и конца: от первой до последней позы/кисти.
 * Если человека не было ни в одном кадре, возвращает `null`.
 */
export function autoTrimRange(
  frames: readonly CapturedFrame[],
  options: AutoTrimOptions = {},
): TrimRange | null {
  if (frames.length === 0) return null;
  const padding = Math.max(0, Math.round(options.paddingFrames ?? 0));
  const minFrames = Math.max(1, Math.round(options.minFrames ?? 2));

  let first = -1;
  let last = -1;
  for (let index = 0; index < frames.length; index += 1) {
    if (frameHasBody(frames[index].frame)) {
      if (first === -1) first = index;
      last = index;
    }
  }
  if (first === -1) return null;

  let start = Math.max(0, first - padding);
  let end = Math.min(frames.length, last + 1 + padding);
  // Короткий жест: добираем кадры после, затем перед, но не выходим за запись.
  if (end - start < minFrames) {
    end = Math.min(frames.length, start + minFrames);
    start = Math.max(0, end - minFrames);
  }
  return { start, end };
}

/** Привести ручной диапазон к допустимым границам и минимальной длине. */
export function clampTrimRange(
  range: TrimRange,
  totalFrames: number,
  minFrames = 2,
): TrimRange {
  if (totalFrames <= 0) return { start: 0, end: 0 };
  const min = Math.min(Math.max(1, Math.round(minFrames)), totalFrames);
  let start = Math.max(0, Math.min(Math.round(range.start), totalFrames - min));
  let end = Math.max(start + min, Math.min(Math.round(range.end), totalFrames));
  if (end > totalFrames) {
    end = totalFrames;
    start = Math.max(0, end - min);
  }
  return { start, end };
}

/**
 * Пересэмплировать выбранные кадры на равномерную частоту. Для каждой целевой
 * метки берётся ближайший по времени кадр — жест не растягивается и не рвётся.
 */
export function resampleCapturedFrames(
  frames: readonly CapturedFrame[],
  fps = RECORD_FPS,
): CapturedFrame[] {
  if (frames.length === 0) return [];
  if (frames.length === 1 || fps <= 0) return [frames[0]];

  const firstTime = frames[0].timeMs;
  const durationMs = Math.max(0, frames[frames.length - 1].timeMs - firstTime);
  const count = Math.max(1, Math.round((durationMs / 1000) * fps));
  const step = 1000 / fps;
  const result: CapturedFrame[] = [];
  let source = 0;

  for (let index = 0; index < count; index += 1) {
    const target = firstTime + index * step;
    while (
      source + 1 < frames.length &&
      Math.abs(frames[source + 1].timeMs - target) <= Math.abs(frames[source].timeMs - target)
    ) {
      source += 1;
    }
    result.push({ timeMs: target, frame: frames[source].frame });
  }
  return result;
}

function resizePart(points: readonly Landmark[], count: number, fallback: Landmark): Landmark[] {
  const result: Landmark[] = [];
  for (let index = 0; index < count; index += 1) {
    result.push(clonePoint(points[index] ?? points[points.length - 1] ?? fallback));
  }
  return result;
}

function neutralHand(wrist: Landmark): Landmark[] {
  const result: Landmark[] = [];
  for (let index = 0; index < 21; index += 1) {
    const finger = Math.floor(index / 5);
    const joint = index % 5;
    result.push(
      point(wrist.x + (finger - 2) * 0.012, wrist.y + joint * 0.01, wrist.z),
    );
  }
  return result;
}

function neutralFace(center: Landmark): Landmark[] {
  const result: Landmark[] = [];
  for (let index = 0; index < 468; index += 1) {
    const angle = index * 2.399963;
    const radius = 0.01 + (index % 7) * 0.003;
    result.push(
      point(
        center.x + Math.cos(angle) * radius,
        center.y + Math.sin(angle) * radius,
        center.z,
      ),
    );
  }
  return result;
}

/**
 * Достроить кадр до полного layout: недостающие кисти/лицо берутся из
 * предыдущего кадра, а если их не было совсем — нейтральная заготовка у запястья.
 */
export function normalizeRecordedFrame(
  frame: HolisticFrame,
  previous: HolisticFrame = emptyFrame(),
): HolisticFrame {
  const poseCenter = frame.pose[0] ?? previous.pose[0] ?? point();
  const leftWrist = frame.pose[15] ?? previous.pose[15] ?? poseCenter;
  const rightWrist = frame.pose[16] ?? previous.pose[16] ?? poseCenter;

  const pose =
    frame.pose.length > 0
      ? resizePart(frame.pose, 33, poseCenter)
      : previous.pose.length > 0
        ? resizePart(previous.pose, 33, poseCenter)
        : Array.from({ length: 33 }, () => clonePoint(poseCenter));

  const leftHand =
    frame.leftHand.length > 0
      ? resizePart(frame.leftHand, 21, leftWrist)
      : previous.leftHand.length > 0
        ? resizePart(previous.leftHand, 21, leftWrist)
        : previous.rightHand.length > 0
          ? resizePart(previous.rightHand, 21, leftWrist)
          : neutralHand(leftWrist);

  const rightHand =
    frame.rightHand.length > 0
      ? resizePart(frame.rightHand, 21, rightWrist)
      : previous.rightHand.length > 0
        ? resizePart(previous.rightHand, 21, rightWrist)
        : previous.leftHand.length > 0
          ? resizePart(previous.leftHand, 21, rightWrist)
          : neutralHand(rightWrist);

  const face =
    frame.face.length > 0
      ? resizePart(frame.face, 468, poseCenter)
      : previous.face.length > 0
        ? resizePart(previous.face, 468, poseCenter)
        : neutralFace(poseCenter);

  return { pose, face, leftHand, rightHand };
}

function toLandmark(value: Vec3): Landmark {
  return { x: value.x, y: value.y, z: value.z };
}

/**
 * Подготовить кадры к упаковке: пересэмплирование уже сделано, здесь — добор
 * частей скелета и One Euro на каждую часть отдельно.
 */
export function prepareRecordedFrames(
  frames: readonly CapturedFrame[],
  fps = RECORD_FPS,
  options: PrepareOptions = {},
): HolisticFrame[] {
  const smoothing = options.smooth ?? true;
  const filters = smoothing
    ? {
        pose: new OneEuroLandmarks({ frequency: fps, ...options.smoothing }),
        hand_l: new OneEuroLandmarks({ frequency: fps, ...options.smoothing }),
        hand_r: new OneEuroLandmarks({ frequency: fps, ...options.smoothing }),
        face: new OneEuroLandmarks({ frequency: fps, ...options.smoothing }),
      }
    : null;

  let previous = emptyFrame();
  return frames.map(({ frame }) => {
    const normalized = normalizeRecordedFrame(frame, previous);
    previous = normalized;
    if (!filters) return normalized;

    return {
      pose: filters.pose.filter(normalized.pose).map(toLandmark),
      leftHand: filters.hand_l.filter(normalized.leftHand).map(toLandmark),
      rightHand: filters.hand_r.filter(normalized.rightHand).map(toLandmark),
      face: filters.face.filter(normalized.face).map(toLandmark),
    };
  });
}

/** Плоский массив `frames × 543 × 3` в порядке layout клипа. */
export function flattenRecordedFrames(frames: readonly HolisticFrame[]): number[] {
  const values: number[] = [];
  for (const frame of frames) {
    for (const part of [frame.pose, frame.leftHand, frame.rightHand, frame.face]) {
      for (const landmark of part) {
        values.push(landmark.x, landmark.y, landmark.z);
      }
    }
  }
  return values;
}

/**
 * Полный конвейер D2: обрезка → 30 FPS → One Euro → Float16/gzip/base64 →
 * `.json.gz`. Бросает ошибку, если в выбранном диапазоне нет кадров.
 */
export async function encodeRecordedClip(
  options: EncodeRecordedClipOptions,
): Promise<EncodedRecordedClip> {
  const fps = options.fps ?? RECORD_FPS;
  const maxFrames = options.maxFrames ?? RECORD_MAX_FRAMES;
  if (!Number.isFinite(fps) || fps <= 0) {
    throw new ClipRecordError("Частота кадров должна быть положительной.");
  }
  if (!Number.isFinite(maxFrames) || maxFrames <= 0) {
    throw new ClipRecordError("Лимит кадров должен быть положительным.");
  }
  if (options.frames.length === 0) {
    throw new ClipRecordError("Запись пуста.");
  }

  const range = clampTrimRange(options.range, options.frames.length, 1);
  const selected = options.frames.slice(range.start, range.end);
  if (!selected.some((item) => frameHasBody(item.frame))) {
    throw new ClipRecordError("В выбранном диапазоне нет позы или кистей.");
  }
  const frameLimit = Math.max(1, Math.round(maxFrames));
  const resampled = resampleCapturedFrames(selected, fps).slice(0, frameLimit);
  if (resampled.length === 0) {
    throw new ClipRecordError("В выбранном диапазоне нет кадров.");
  }

  const prepared = prepareRecordedFrames(resampled, fps, {
    smooth: options.smooth,
    smoothing: options.smoothing,
  });
  const values = flattenRecordedFrames(prepared);
  const payload = await encodeClipPayload({
    gloss: options.gloss?.trim() || "ЗАПИСЬ",
    fps,
    frames: prepared.length,
    layout: RECORD_LAYOUT,
    values,
  });
  const file = await packClipFile(payload);

  return {
    payload,
    file,
    frameCount: prepared.length,
    durationMs: Math.round((prepared.length / fps) * 1000),
  };
}
