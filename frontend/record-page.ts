/**
 * Инструмент записи жестов (D1): камера и предпросмотр скелета MediaPipe.
 *
 * Страница `GET /dictionary/record/` открывает камеру по кнопке и рисует поверх
 * видео позу, лицо и кисти. Запись и упаковка клипа появятся на следующем этапе
 * (D2); здесь важно, чтобы скелет следовал за рукой в реальном времени.
 */

import {
  HolisticDetector,
  framePointCount,
  handsDetected,
} from "./holistic";
import { drawSkeleton, type HolisticFrame, type Viewport } from "./skeleton";

type StatusState = "idle" | "loading" | "running" | "warning" | "error";

const STATUS_LABELS: Record<StatusState, string> = {
  idle: "Камера выключена",
  loading: "Включение камеры…",
  running: "Камера работает",
  warning: "Камера работает, но скелет недоступен",
  error: "Ошибка камеры",
};

function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}

function setupRecordPage(root: HTMLElement): void {
  const stage = root.querySelector<HTMLElement>("[data-record-stage]");
  const video = root.querySelector<HTMLVideoElement>("[data-record-video]");
  const canvas = root.querySelector<HTMLCanvasElement>("[data-record-canvas]");
  const startButton = root.querySelector<HTMLButtonElement>("[data-record-start]");
  const stopButton = root.querySelector<HTMLButtonElement>("[data-record-stop]");
  const status = root.querySelector<HTMLElement>("[data-record-status]");
  const stats = root.querySelector<HTMLElement>("[data-record-stats]");
  const hands = root.querySelector<HTMLElement>("[data-record-hands]");
  if (!video || !canvas) return;

  const context = canvas.getContext("2d");
  const wasmBasePath = root.dataset.mediapipeWasm?.trim() ?? "";
  const modelUrl = root.dataset.mediapipeModelUrl?.trim() ?? "";

  let stream: MediaStream | null = null;
  let detector: HolisticDetector | null = null;
  let detectorPromise: Promise<HolisticDetector | null> | null = null;
  let animationFrame = 0;
  let lastVideoTime = -1;
  let lastTimestamp = 0;
  let lastFrame: HolisticFrame | null = null;
  let lastStatsAt = 0;
  let detectTimes: number[] = [];
  let detectError: string | null = null;
  let disposed = false;

  const setStatus = (state: StatusState, detail?: string): void => {
    if (!status) return;
    status.dataset.state = state;
    status.textContent = detail ? `${STATUS_LABELS[state]}: ${detail}` : STATUS_LABELS[state];
  };

  const setBusy = (running: boolean): void => {
    if (startButton) startButton.disabled = running;
    if (stopButton) stopButton.disabled = !running;
  };

  const viewport = (): Viewport | null => {
    const width = Math.round(video.clientWidth);
    const height = Math.round(video.clientHeight);
    if (width <= 0 || height <= 0 || video.videoWidth <= 0 || video.videoHeight <= 0) {
      return null;
    }
    return {
      width,
      height,
      videoWidth: video.videoWidth,
      videoHeight: video.videoHeight,
      mirror: true,
    };
  };

  const resizeCanvas = (): void => {
    const ratio = window.devicePixelRatio || 1;
    const width = Math.max(1, Math.round(video.clientWidth * ratio));
    const height = Math.max(1, Math.round(video.clientHeight * ratio));
    if (canvas.width === width && canvas.height === height) return;
    canvas.width = width;
    canvas.height = height;
    if (context) context.setTransform(ratio, 0, 0, ratio, 0, 0);
  };

  const drawCurrentFrame = (): void => {
    if (!context) return;
    const box = viewport();
    if (!box) return;
    context.clearRect(0, 0, box.width, box.height);
    if (lastFrame) drawSkeleton(context, lastFrame, box);
  };

  const updateStats = (now: number): void => {
    if (!stats) return;
    if (now - lastStatsAt < 400) return;
    lastStatsAt = now;

    if (!lastFrame || framePointCount(lastFrame) === 0) {
      stats.textContent = detector ? "В кадре пока нет человека" : "Скелет не подключён";
      if (hands) hands.textContent = "Кисти: —";
      return;
    }

    detectTimes = detectTimes.filter((time) => now - time <= 1000);
    const seen = handsDetected(lastFrame);
    stats.textContent =
      `Поза: ${lastFrame.pose.length} · лицо: ${lastFrame.face.length} · ` +
      `${detectTimes.length} кадр/с`;
    if (hands) {
      const visible = [seen.left ? "левая" : null, seen.right ? "правая" : null].filter(
        (value): value is string => value !== null,
      );
      hands.textContent = visible.length > 0 ? `Кисти: ${visible.join(" и ")}` : "Кисти: не видны";
    }
  };

  const render = (): void => {
    resizeCanvas();
    drawCurrentFrame();
  };

  const loadDetector = (): Promise<HolisticDetector | null> => {
    if (detector) return Promise.resolve(detector);
    if (detectorPromise) return detectorPromise;
    detectorPromise = (async () => {
      if (stream) {
        setStatus(
          "running",
          "камера включена, загружается скелет MediaPipe (первый раз может занять время)",
        );
      }
      try {
        const created = await HolisticDetector.create({ wasmBasePath, modelUrl });
        if (disposed) {
          created.dispose();
          return null;
        }
        detector = created;
        detectError = null;
        return detector;
      } catch (error) {
        detectError = errorMessage(error);
        if (stream) setStatus("warning", detectError);
        return null;
      } finally {
        detectorPromise = null;
      }
    })();
    return detectorPromise;
  };

  const loop = (now: number): void => {
    animationFrame = requestAnimationFrame(loop);
    if (video.readyState < 2) return;

    if (detector && video.currentTime !== lastVideoTime) {
      lastVideoTime = video.currentTime;
      // Метка должна строго расти даже при двух вызовах в одном кадре.
      lastTimestamp = Math.max(now, lastTimestamp + 1);
      try {
        lastFrame = detector.detect(video, lastTimestamp);
        detectTimes.push(now);
        render();
      } catch (error) {
        // Один сбой не должен ронять предпросмотр камеры: показываем причину и
        // отключаем детектор до повторного запуска.
        detectError = errorMessage(error);
        detector.dispose();
        detector = null;
        lastFrame = null;
        setStatus("warning", `сбой MediaPipe: ${detectError}`);
      }
    }
    updateStats(now);
  };

  const stopLoop = (): void => {
    if (animationFrame) {
      cancelAnimationFrame(animationFrame);
      animationFrame = 0;
    }
  };

  const clearCanvas = (): void => {
    if (context) context.clearRect(0, 0, canvas.width, canvas.height);
    lastFrame = null;
    detectTimes = [];
  };

  const stopCamera = (): void => {
    stopLoop();
    stream?.getTracks().forEach((track) => track.stop());
    stream = null;
    video.srcObject = null;
    stage?.classList.remove("is-live");
    clearCanvas();
    setBusy(false);
    setStatus("idle");
    if (stats) stats.textContent = "Скелет не подключён";
    if (hands) hands.textContent = "Кисти: —";
  };

  const startCamera = async (): Promise<void> => {
    if (stream) return;
    setBusy(true);
    setStatus("loading", "запрос доступа к камере");
    clearCanvas();

    try {
      if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error("Браузер не поддерживает доступ к камере (нужен HTTPS или localhost).");
      }
      stream = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: "user",
          width: { ideal: 1280 },
          height: { ideal: 720 },
        },
        audio: false,
      });
      video.srcObject = stream;
      await video.play();
      stage?.classList.add("is-live");
      render();
      setStatus("running");
      // Модель грузится параллельно: видео появляется сразу, скелет — как только
      // будет готов WASM. Ошибка модели не мешает смотреть камеру.
      void loadDetector().then((loaded) => {
        if (loaded && stream) setStatus("running");
      });
      animationFrame = requestAnimationFrame(loop);
    } catch (error) {
      stopCamera();
      setStatus("error", errorMessage(error));
    }
  };

  startButton?.addEventListener("click", () => {
    void startCamera();
  });
  stopButton?.addEventListener("click", stopCamera);

  // Поворот телефона или изменение размера окна: холст должен совпасть с видео.
  window.addEventListener("resize", render);

  window.addEventListener(
    "pagehide",
    () => {
      disposed = true;
      stopCamera();
      detector?.dispose();
      detector = null;
      window.removeEventListener("resize", render);
    },
    { once: true },
  );
}

function init(): void {
  document.querySelectorAll<HTMLElement>("[data-record-page]").forEach(setupRecordPage);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init, { once: true });
} else {
  init();
}
