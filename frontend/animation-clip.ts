/**
 * Анимационные клипы (H1): загрузка готовой анимации VRMA/glTF.
 *
 * Второй формат клипа рядом с landmarks (`clip.ts`). Файл — бинарный glTF
 * (GLB): заголовок, JSON-чанк с метаданными и, обычно, BIN-чанк с дорожками.
 * Сервер такой файл только проверяет и хранит, а браузер разбирает через
 * `GLTFLoader` и играет `AnimationMixer`-ом (`animation-player.ts`).
 *
 * VRMA (`.vrma`) — GLB с расширением `VRMC_vrm_animation`: дорожки адресуют
 * гуманоидные кости VRM, а не узлы конкретной модели. Такие файлы грузятся
 * через `VRMAnimationLoaderPlugin` из `@pixiv/three-vrm-animation`, который
 * кладёт разобранные записи в `gltf.userData.vrmAnimations`. Затем
 * `createVRMAnimationClip` разворачивает их в `AnimationClip` уже **под
 * конкретную модель** — поэтому для VRMA в загрузчик передаётся `vrm`.
 */

import type { VRM } from "@pixiv/three-vrm";
import { createVRMAnimationClip } from "@pixiv/three-vrm-animation";
import { VRMAnimationLoaderPlugin } from "@pixiv/three-vrm-animation";
import type { VRMAnimation } from "@pixiv/three-vrm-animation";
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

/** Файл — VRMA, но модель для ретаргета не передана. */
export class VrmaNotSupportedError extends AnimationFormatError {
  constructor() {
    super(
      "Клип VRMA нужно разворачивать под конкретную VRM-модель: " +
        "передайте `vrm` в loadAnimationBundle (см. room-phrase.ts).",
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

/**
 * Выбрать запись из файла по имени (`SignClip.animation_name`).
 *
 * Пустое имя — первая анимация (файл с одним жестом). Если имя задано, но
 * такой записи нет, возвращается `null`: лучше показать субтитры, чем
 * сыграть не тот жест. Имена совпадают с `animations[].name` в glTF.
 */
export function pickAnimationClip(
  bundle: AnimationBundle,
  name?: string | null,
): AnimationClip | null {
  if (bundle.clips.length === 0) return null;
  const wanted = (name ?? "").trim();
  if (!wanted) return bundle.clips[0];
  return bundle.clips.find((clip) => clip.name === wanted) ?? null;
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
 * Перенести имена записей glTF в клипы VRM.
 *
 * `createVRMAnimationClip` из three-vrm всегда называет клип "Clip" и теряет
 * имя записи. В файле с несколькими анимациями (жест = именованная запись)
 * выбор по имени (`pickAnimationClip`) без этого не работает. Порядок
 * `vrmAnimations` совпадает с `gltf.animations`.
 */
export function nameVrmaClips(
  clips: AnimationClip[],
  names: ReadonlyArray<string | undefined>,
): AnimationClip[] {
  clips.forEach((clip, index) => {
    const name = names[index];
    if (name) clip.name = name;
  });
  return clips;
}

/**
 * Загрузить один файл анимации и вернуть дорожки для `AnimationMixer`.
 *
 * Обычный GLB содержит анимации на узлах модели и разбирается как есть. VRMA
 * адресует гуманоидные кости (`VRMC_vrm_animation`), поэтому его нужно
 * развернуть под конкретную модель: вызовите с `vrm` (моделью страницы).
 * Без `vrm` на VRMA бросается `VrmaNotSupportedError` — лучше понятная ошибка,
 * чем жест, сыгранный на чужих костях.
 */
export async function loadAnimationBundle(
  url: string,
  options: { fetcher?: AnimationFetcher; vrm?: VRM | null } = {},
): Promise<AnimationBundle> {
  const fetcher = options.fetcher ?? fetchBytes;
  const buffer = await fetcher(url);
  const payload = jsonFromGlb(buffer);
  const vrma = isVrmaJson(payload);
  if (animationCount(payload) === 0) {
    throw new AnimationFormatError("В файле анимации нет ни одной анимации.");
  }

  const basePath = url.slice(0, url.lastIndexOf("/") + 1);
  const loader = new GLTFLoader();
  if (vrma) {
    if (!options.vrm) {
      throw new VrmaNotSupportedError();
    }
    loader.register((parser) => new VRMAnimationLoaderPlugin(parser));
  }
  const gltf = await loader.parseAsync(buffer, basePath);

  if (vrma) {
    const vrm = options.vrm as VRM;
    const animations = (gltf.userData.vrmAnimations as VRMAnimation[] | undefined) ?? [];
    const clips = nameVrmaClips(
      animations.map((animation) => createVRMAnimationClip(animation, vrm)),
      gltf.animations.map((clip) => clip.name),
    ).filter((clip) => clip.tracks.length > 0);
    if (clips.length === 0) {
      throw new AnimationFormatError("VRMA не дал ни одной дорожки для этой модели.");
    }
    return { clips, vrma, url };
  }

  if (gltf.animations.length === 0) {
    throw new AnimationFormatError("GLTFLoader не нашёл анимаций в файле.");
  }
  return { clips: gltf.animations, vrma, url };
}
