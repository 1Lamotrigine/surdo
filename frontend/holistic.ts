/**
 * MediaPipe Holistic в браузере (D1).
 *
 * Загружает WASM и модель один раз, обрабатывает кадры видео и приводит ответ
 * задачи к простому `HolisticFrame` (поза, лицо, кисти). Видео не покидает
 * браузер: на сервер уходят только landmarks на следующем этапе записи (D2).
 *
 * Модуль зависит от DOM только в `HolisticDetector.create` и `detect`: разбор
 * ответа и проверки покрыты vitest в Node.
 */

import type { HolisticFrame, Landmark } from "./skeleton";

export type HolisticRawResult = {
  poseLandmarks?: unknown;
  faceLandmarks?: unknown;
  leftHandLandmarks?: unknown;
  rightHandLandmarks?: unknown;
};

export type HolisticDetectorOptions = {
  /** Каталог с `vision_wasm_internal.js` и `.wasm` (собирает Vite). */
  wasmBasePath: string;
  /** URL файла `holistic_landmarker.task`. */
  modelUrl: string;
  /** Порог уверенности для кистей, по умолчанию 0.5. */
  minHandLandmarksConfidence?: number;
};

/** Ошибка загрузки WASM/модели — показывается в интерфейсе редактора. */
export class HolisticLoadError extends Error {
  constructor(message: string, options?: ErrorOptions) {
    super(message, options);
    this.name = "HolisticLoadError";
  }
}

function normalizeLandmark(value: unknown): Landmark | null {
  if (typeof value !== "object" || value === null) return null;
  const point = value as Record<string, unknown>;
  if (typeof point.x !== "number" || typeof point.y !== "number") return null;
  const landmark: Landmark = {
    x: point.x,
    y: point.y,
    z: typeof point.z === "number" ? point.z : 0,
  };
  if (typeof point.visibility === "number") landmark.visibility = point.visibility;
  return landmark;
}

/**
 * Привести набор точек MediaPipe к массиву. Задача отдаёт `NormalizedLandmark[][]`
 * (по человеку/руке на элемент), но исторически встречается и плоский массив.
 */
export function normalizeLandmarkSet(value: unknown): Landmark[] {
  if (!Array.isArray(value) || value.length === 0) return [];
  const first = value[0];
  const list: unknown[] =
    typeof first === "object" && first !== null && "x" in first ? value : (first as unknown[]);
  if (!Array.isArray(list)) return [];
  const result: Landmark[] = [];
  for (const item of list) {
    const landmark = normalizeLandmark(item);
    if (landmark) result.push(landmark);
  }
  return result;
}

/** Ответ `HolisticLandmarker.detectForVideo` → один кадр скелета. */
export function normalizeHolisticResult(result: HolisticRawResult): HolisticFrame {
  return {
    pose: normalizeLandmarkSet(result.poseLandmarks),
    face: normalizeLandmarkSet(result.faceLandmarks),
    leftHand: normalizeLandmarkSet(result.leftHandLandmarks),
    rightHand: normalizeLandmarkSet(result.rightHandLandmarks),
  };
}

/** Есть ли в кадре хоть одна точка — индикатор для интерфейса. */
export function framePointCount(frame: HolisticFrame): number {
  return frame.pose.length + frame.face.length + frame.leftHand.length + frame.rightHand.length;
}

/** Кисти, которые MediaPipe увидел в кадре. */
export function handsDetected(frame: HolisticFrame): { left: boolean; right: boolean } {
  return {
    left: frame.leftHand.length >= 21,
    right: frame.rightHand.length >= 21,
  };
}

type LandmarkerLike = {
  detectForVideo(video: HTMLVideoElement, timestampMs: number): HolisticRawResult;
  close(): void;
};

/**
 * Обёртка над `HolisticLandmarker`: ленивая загрузка пакета, повтор с CPU при
 * ошибке GPU и защита от немонотонных меток времени.
 */
export class HolisticDetector {
  private readonly landmarker: LandmarkerLike;
  private lastTimestamp = -1;

  private constructor(landmarker: LandmarkerLike) {
    this.landmarker = landmarker;
  }

  static async create(options: HolisticDetectorOptions): Promise<HolisticDetector> {
    if (!options.modelUrl) {
      throw new HolisticLoadError("Не задан URL модели MediaPipe Holistic.");
    }
    if (!options.wasmBasePath) {
      throw new HolisticLoadError("Не задан путь к WASM MediaPipe.");
    }

    let vision: typeof import("@mediapipe/tasks-vision");
    try {
      vision = await import("@mediapipe/tasks-vision");
    } catch (error) {
      throw new HolisticLoadError("Не удалось загрузить библиотеку MediaPipe.", {
        cause: error,
      });
    }

    let fileset;
    try {
      fileset = await vision.FilesetResolver.forVisionTasks(options.wasmBasePath);
    } catch (error) {
      throw new HolisticLoadError("Не удалось загрузить WASM MediaPipe.", { cause: error });
    }

    const createOptions = (delegate: "GPU" | "CPU") => ({
      baseOptions: {
        modelAssetPath: options.modelUrl,
        delegate,
      },
      runningMode: "VIDEO" as const,
      minHandLandmarksConfidence: options.minHandLandmarksConfidence ?? 0.5,
    });

    let landmarker;
    try {
      landmarker = await vision.HolisticLandmarker.createFromOptions(
        fileset,
        createOptions("GPU"),
      );
    } catch (gpuError) {
      // На части ноутбуков и в Firefox WebGL-делегат недоступен — CPU медленнее,
      // но предпросмотр скелета остаётся рабочим.
      try {
        landmarker = await vision.HolisticLandmarker.createFromOptions(
          fileset,
          createOptions("CPU"),
        );
      } catch (cpuError) {
        throw new HolisticLoadError(
          "Не удалось загрузить модель MediaPipe Holistic. Проверьте URL модели.",
          { cause: cpuError instanceof Error ? cpuError : gpuError },
        );
      }
    }

    return new HolisticDetector(landmarker as unknown as LandmarkerLike);
  }

  /**
   * Обработать текущий кадр видео. Метка времени должна расти: MediaPipe в
   * режиме VIDEO выбрасывает кадр с неподходящим временем.
   */
  detect(video: HTMLVideoElement, timestampMs: number): HolisticFrame {
    const timestamp = Math.max(Math.round(timestampMs), this.lastTimestamp + 1);
    this.lastTimestamp = timestamp;
    return normalizeHolisticResult(this.landmarker.detectForVideo(video, timestamp));
  }

  dispose(): void {
    this.landmarker.close();
  }
}
