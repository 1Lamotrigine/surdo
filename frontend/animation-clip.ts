/**
 * Анимационные клипы (H1): загрузка готовой анимации VRMA/glTF.
 *
 * Второй формат клипа рядом с landmarks (`clip.ts`). Файл — бинарный glTF
 * (GLB): заголовок, JSON-чанк с метаданными и, обычно, BIN-чанк с дорожками.
 * Сервер такой файл только проверяет и хранит, а браузер разбирает через
 * `GLTFLoader` и играет `AnimationMixer`-ом (`animation-player.ts`).
 *
 * VRMA (`.vrma`) — GLB с расширением `VRMC_vrm_animation`: дорожки адресуют
 * гуманоидные кости VRM, а не узлы конкретной модели. Для него нужен
 * `@pixiv/three-vrm-animation`; пакет пока не подключён, поэтому загрузчик
 * честно сообщает об этом (`VrmaNotSupportedError`), а не падает молча.
 * Подключение — один шаг, см. `docs/ANIMATIONS.md`, раздел «VRMA».
 */

import type { AnimationClip } from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";

/** Разобранный набор анимаций из одного файла. */
export type AnimationBundle = {
  /** Дорожки для `AnimationMixer`; для одного жеста обычно одна. */
  clips: AnimationClip[];
  /** Файл размечен как VRMA. */
  vrma: boolean;
  /** Исходный URL (для диагностики). */
  url: string;
};

/** Файл не является корректным GLB/анимацией. */
export class AnimationFormatError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "AnimationFormatError";
  }
}

/** Файл — VRMA, но пакет `@pixiv/three-vrm-animation` не подключён. */
export class VrmaNotSupportedError extends AnimationFormatError {
  constructor() {
    super(
      "Клип VRMA требует пакета @pixiv/three-vrm-animation. " +
        "Подключите его и включите VRMAnimationLoaderPlugin (docs/ANIMATIONS.md).",
    );
    this.name = "VrmaNotSupportedError";
  }
}

const GLB_MAGIC = 0x46546c67; // 'glTF' little-endian
const GLB_JSON_CHUNK = 0x4e4f534a; // 'JSON'
const GLB_HEADER_SIZE = 12;
const GLB_CHUNK_HEADER_SIZE = 8;
const VRMA_EXTENSION = "VRMC_vrm_animation";

function jsonFromGlb(buffer: ArrayBuffer): Record<string, unknown> {
  if (buffer.byteLength < GLB_HEADER_SIZE) {
    throw new AnimationFormatError("Файл анимации короче заголовка GLB.");
  }
  const view = new DataView(buffer);
  if (view.getUint32(0, true) !== GLB_MAGIC) {
    throw new AnimationFormatError("Файл анимации не является GLB (нет сигнатуры glTF).");
  }
  const version = view.getUint32(4, true);
  if (version !== 2) {
    throw new AnimationFormatError(`Версия GLB ${version} не поддерживается (ожидается 2).`);
  }
  const length = view.getUint32(8, true);
  if (length !== buffer.byteLength) {
    throw new AnimationFormatError("Длина GLB в заголовке не совпадает с размером файла.");
  }
  if (GLB_HEADER_SIZE + GLB_CHUNK_HEADER_SIZE > buffer.byteLength) {
    throw new AnimationFormatError("В GLB нет JSON-чанка.");
  }
  const chunkLength = view.getUint32(GLB_HEADER_SIZE, true);
  const chunkType = view.getUint32(GLB_HEADER_SIZE + 4, true);
  if (chunkType !== GLB_JSON_CHUNK) {
    throw new AnimationFormatError("Первый чанк GLB должен быть JSON.");
  }
  const start = GLB_HEADER_SIZE + GLB_CHUNK_HEADER_SIZE;
  if (start + chunkLength > buffer.byteLength) {
    throw new AnimationFormatError("JSON-чанк GLB выходит за границы файла.");
  }
  const text = new TextDecoder().decode(new Uint8Array(buffer, start, chunkLength));
  try {
    const payload = JSON.parse(text.replace(/[\u0000\s]+$/u, ""));
    if (typeof payload !== "object" || payload === null || Array.isArray(payload)) {
      throw new Error("not an object");
    }
    return payload as Record<string, unknown>;
  } catch {
    throw new AnimationFormatError("JSON-чанк GLB не разбирается.");
  }
}

/** JSON-чанк GLB или `null`, если файл не GLB (не бросает исключение). */
export function glbJson(buffer: ArrayBuffer): Record<string, unknown> | null {
  try {
    return jsonFromGlb(buffer);
  } catch {
    return null;
  }
}

/** Является ли JSON-чанк VRMA (расширение `VRMC_vrm_animation`). */
export function isVrmaJson(payload: Record<string, unknown>): boolean {
  const used = payload.extensionsUsed;
  return Array.isArray(used) && used.includes(VRMA_EXTENSION);
}

/** Число анимаций в JSON-чанке (0, если поля нет). */
export function animationCount(payload: Record<string, unknown>): number {
  return Array.isArray(payload.animations) ? payload.animations.length : 0;
}

/** Загрузчик байтов (подменяется в тестах). */
export type AnimationFetcher = (url: string) => Promise<ArrayBuffer>;

async function fetchBytes(url: string): Promise<ArrayBuffer> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new AnimationFormatError(`Анимация не загружена: HTTP ${response.status}`);
  }
  return response.arrayBuffer();
}

/**
 * Загрузить один файл анимации и вернуть дорожки для `AnimationMixer`.
 *
 * Сейчас поддерживается обычный GLB с анимациями на узлах модели. VRMA
 * распознаётся и даёт понятную ошибку до подключения пакета ретаргета.
 */
export async function loadAnimationBundle(
  url: string,
  options: { fetcher?: AnimationFetcher } = {},
): Promise<AnimationBundle> {
  const fetcher = options.fetcher ?? fetchBytes;
  const buffer = await fetcher(url);
  const payload = jsonFromGlb(buffer);
  const vrma = isVrmaJson(payload);
  if (vrma) {
    throw new VrmaNotSupportedError();
  }
  if (animationCount(payload) === 0) {
    throw new AnimationFormatError("В файле анимации нет ни одной анимации.");
  }

  const basePath = url.slice(0, url.lastIndexOf("/") + 1);
  const gltf = await new GLTFLoader().parseAsync(buffer, basePath);
  if (gltf.animations.length === 0) {
    throw new AnimationFormatError("GLTFLoader не нашёл анимаций в файле.");
  }
  return { clips: gltf.animations, vrma, url };
}
