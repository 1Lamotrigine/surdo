/**
 * Модуль аватара (C1): сцена Three.js, свет, камера и загрузка VRM
 * через `@pixiv/three-vrm`. Модуль сам не знает про клипы: он умеет
 * показать модель в нейтральной позе и отдать её для ретаргета (C3).
 *
 * Требования: `docs/spec/clip-format.md` (5.4), `docs/spec/requirements.md` (FR-11).
 */

import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { VRM, VRMLoaderPlugin, VRMUtils } from "@pixiv/three-vrm";

import { resetToNeutral } from "./vrm-rig";

export type AvatarStatus = "loading" | "ready" | "error";

export type AvatarOptions = {
  /** Корневой элемент, внутри которого создаётся canvas. */
  container: HTMLElement;
  /** URL модели `.vrm`. Если не задан, сцена рисуется без модели. */
  modelUrl?: string;
  /** Цвет фона сцены (тёмный фон по умолчанию — FR-13). */
  background?: THREE.ColorRepresentation;
  /** Вызывается при смене состояния загрузки модели. */
  onStatus?: (status: AvatarStatus, detail?: string) => void;
};

// Нейтральная поза: руки вниз задаёт `resetToNeutral` (см. `vrm-rig`).

const DEFAULT_BACKGROUND: THREE.ColorRepresentation = 0x111827;

// Кадр камеры: показываем от бёдер до макушки — ноги в жестах не участвуют.
// Рост человека ≈ 1.81 м, бедро — примерно на 0.52 роста; кадр начинается чуть
// ниже бедра, чтобы жест «от бедра» не обрезался. Запас сверху — на поднятую
// в махе руку (≈111% роста).
const FRAME_BOTTOM_RATIO = 0.45;
const FRAME_TOP_RATIO = 1.12;
const ARM_SPAN_RATIO = 0.7;

/**
 * 3D-аватар в браузере (WebGL, без установки — FR-11).
 *
 * Жизненный цикл: `new Avatar(container)` → `await load(url)` → анимация кадра.
 * `dispose()` освобождает WebGL-ресурсы и останавливает цикл отрисовки.
 */
export class Avatar {
  readonly renderer: THREE.WebGLRenderer;
  readonly scene: THREE.Scene;
  readonly camera: THREE.PerspectiveCamera;

  private readonly container: HTMLElement;
  private readonly clock: THREE.Clock;
  private readonly loader: GLTFLoader;
  private readonly onStatus?: AvatarOptions["onStatus"];
  private frameId: number | null = null;
  private vrm: VRM | null = null;
  private disposed = false;

  constructor(options: AvatarOptions) {
    this.container = options.container;
    this.onStatus = options.onStatus;
    this.clock = new THREE.Clock();

    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.setSize(this.container.clientWidth || 640, this.container.clientHeight || 480);
    this.container.append(this.renderer.domElement);

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(options.background ?? DEFAULT_BACKGROUND);

    // Камера настраивается под модель в `frameCamera` (кадр от бёдер до
    // макушки); значения ниже — только стартовая позиция до загрузки VRM.
    this.camera = new THREE.PerspectiveCamera(
      30,
      (this.container.clientWidth || 640) / (this.container.clientHeight || 480),
      0.1,
      20,
    );
    this.camera.position.set(0, 1.3, 1.6);
    this.camera.lookAt(0, 1.25, 0);

    this.setupLights();
    this.loader = new GLTFLoader();
    this.loader.register((parser) => new VRMLoaderPlugin(parser));

    window.addEventListener("resize", this.handleResize);
  }

  /** Мягкий свет: рассеянный + ключевой + подсветка контура (C1). */
  private setupLights(): void {
    const ambient = new THREE.AmbientLight(0xffffff, 0.9);
    this.scene.add(ambient);

    const key = new THREE.DirectionalLight(0xffffff, 1.2);
    key.position.set(0.6, 1.8, 1.2);
    this.scene.add(key);

    const rim = new THREE.DirectionalLight(0xbfd4ff, 0.6);
    rim.position.set(-1.2, 1.4, -1.6);
    this.scene.add(rim);

    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x444455, 0.5));
  }

  /**
   * Загрузить VRM-модель и поставить её в нейтральную позу.
   * Без `url` сцена остаётся пустой (свет и камера готовы к модели).
   */
  async load(url?: string): Promise<void> {
    this.startLoop();
    if (!url) {
      this.onStatus?.("ready", "Модель не загружена: сцена и камера готовы");
      return;
    }

    this.onStatus?.("loading", "Загрузка модели…");
    try {
      const gltf = await this.loader.loadAsync(url);
      const vrm = gltf.userData.vrm as VRM | undefined;
      if (!vrm) {
        throw new Error("Файл не распознан как VRM");
      }
      if (this.disposed) return;

      // Оптимизация three-vrm: меньше костей и морф-целей — плавнее на телефоне.
      VRMUtils.removeUnnecessaryVertices(gltf.scene);
      VRMUtils.combineSkeletons(gltf.scene);
      VRMUtils.combineMorphs(vrm);
      // VRM 0.x смотрит в -Z; поворот на 180° ставит модель лицом к камере.
      VRMUtils.rotateVRM0(vrm);

      this.setNeutralPose(vrm);
      this.setVrm(vrm);
      this.frameCamera(vrm);
      this.onStatus?.("ready", "Модель загружена");
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      this.onStatus?.("error", detail);
    }
  }

  /** Добавить загруженную модель в сцену, заменив прежнюю. */
  private setVrm(vrm: VRM): void {
    if (this.vrm) {
      this.scene.remove(this.vrm.scene);
      VRMUtils.deepDispose(this.vrm.scene);
    }
    this.vrm = vrm;
    this.scene.add(vrm.scene);
  }

  /** Текущая модель (для ретаргета landmarks в C3). */
  get model(): VRM | null {
    return this.vrm;
  }

  /** Сменить цвет фона сцены (C7: тёмный/светлый фон — FR-13). */
  setBackground(background: THREE.ColorRepresentation): void {
    this.scene.background = new THREE.Color(background);
  }

  /**
   * Поставить модель в нейтральную позу: руки вниз (не T-поза) и нулевая
   * мимика. Именно `resetNormalizedPose()` внутри `resetToNeutral`, а не
   * `setNormalizedPose(normalizedRestPose)`: последний принимает трансформы
   * **относительно** rest pose, и передача в него самого rest pose задваивает
   * трансляции — модель вырастает вдвое и «улетает» вверх.
   */
  setNeutralPose(vrm: VRM | null = this.vrm): void {
    if (!vrm) return;
    resetToNeutral(vrm);
  }

  /**
   * Подогнать камеру под жест: в кадр входят бёдра, торс и **поднятые руки**.
   *
   * Жесты показываются руками, ноги в них не участвуют, поэтому кадр обрезан
   * снизу примерно по бедру, а сверху идёт с запасом: рука, поднятая в махе,
   * доходит примерно до 1.1 роста — выше макушки. Так голова и руки занимают
   * больше экрана и жест читается лучше, чем в кадре «в полный рост».
   */
  private frameCamera(vrm: VRM): void {
    const box = new THREE.Box3().setFromObject(vrm.scene);
    if (box.isEmpty()) return;

    const height = box.max.y - box.min.y;
    // Границы кадра в мировых координатах: от бедра до запаса над макушкой.
    const bottom = box.min.y + height * FRAME_BOTTOM_RATIO;
    const top = box.min.y + height * FRAME_TOP_RATIO;
    const targetHeight = top - bottom;
    const centerY = (top + bottom) / 2;

    const fovRad = THREE.MathUtils.degToRad(this.camera.fov);
    // Дистанция по вертикали: в кадр входит выбранная часть модели.
    let distance = targetHeight / (2 * Math.tan(fovRad / 2));
    // Плюс проверка по горизонтали: руки в стороны не должны упираться в края.
    const armWidth = height * ARM_SPAN_RATIO;
    const halfHRad = Math.atan(Math.tan(fovRad / 2) * this.camera.aspect);
    const distanceForWidth = armWidth / (2 * Math.tan(halfHRad));
    distance = Math.max(distance, distanceForWidth);
    distance *= 1.08;

    this.camera.position.set(0, centerY, distance);
    this.camera.lookAt(0, centerY, 0);
  }

  private startLoop(): void {
    if (this.frameId !== null) return;
    const render = (): void => {
      if (this.disposed) return;
      this.frameId = window.requestAnimationFrame(render);
      const delta = this.clock.getDelta();
      // VRM обновляет spring bones, look-at и материалы — без этого модель «застывает».
      this.vrm?.update(delta);
      this.renderer.render(this.scene, this.camera);
    };
    this.frameId = window.requestAnimationFrame(render);
  }

  private handleResize = (): void => {
    const width = this.container.clientWidth || 640;
    const height = this.container.clientHeight || 480;
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(width, height);
    // Кадр зависит от соотношения сторон (портрет/ландшафт) — пересобираем.
    if (this.vrm) this.frameCamera(this.vrm);
  };

  /** Освободить ресурсы: цикл, слушатели, WebGL-контекст и модель. */
  dispose(): void {
    this.disposed = true;
    window.removeEventListener("resize", this.handleResize);
    if (this.frameId !== null) {
      window.cancelAnimationFrame(this.frameId);
      this.frameId = null;
    }
    if (this.vrm) {
      this.scene.remove(this.vrm.scene);
      VRMUtils.deepDispose(this.vrm.scene);
      this.vrm = null;
    }
    this.renderer.dispose();
    this.renderer.domElement.remove();
  }
}
