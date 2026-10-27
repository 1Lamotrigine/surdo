/**
 * Точка входа тестовой страницы аватара (C1 + C3): `GET /avatar/`.
 * Создаёт `Avatar`, грузит VRM по адресу из поля, а затем может проиграть клип:
 * синтетический (машущие пальцы) или из файла `.json.gz`.
 */

import { Avatar, type AvatarStatus } from "./avatar";
import { decodeClip, decodeClipPayload, type DecodedClip } from "./clip";
import { ClipPlayer } from "./clip-player";
import { encodeDemoClip, encodeDemoQueue } from "./demo-clip";

const STATUS_LABELS: Record<AvatarStatus, string> = {
  loading: "Загрузка…",
  ready: "Готово",
  error: "Ошибка",
};

function setupAvatarPage(root: HTMLElement): void {
  const stage = root.querySelector<HTMLElement>("[data-avatar-stage]");
  const status = root.querySelector<HTMLElement>("[data-avatar-status]");
  const form = root.querySelector<HTMLFormElement>("[data-avatar-form]");
  const urlInput = root.querySelector<HTMLInputElement>("[data-avatar-url]");
  const demoButton = root.querySelector<HTMLButtonElement>("[data-avatar-demo]");
  const queueButton = root.querySelector<HTMLButtonElement>("[data-avatar-queue]");
  const playButton = root.querySelector<HTMLButtonElement>("[data-avatar-play]");
  const stopButton = root.querySelector<HTMLButtonElement>("[data-avatar-stop]");
  const speedInput = root.querySelector<HTMLInputElement>("[data-avatar-speed]");
  const gapInput = root.querySelector<HTMLInputElement>("[data-avatar-gap]");
  const fileInput = root.querySelector<HTMLInputElement>("[data-avatar-file]");
  const clipStatus = root.querySelector<HTMLElement>("[data-clip-status]");
  if (!stage) return;

  const setStatus = (state: AvatarStatus, detail?: string): void => {
    if (!status) return;
    status.dataset.state = state;
    status.textContent = detail ? `${STATUS_LABELS[state]}: ${detail}` : STATUS_LABELS[state];
  };

  const setClipStatus = (text: string): void => {
    if (clipStatus) clipStatus.textContent = text;
  };

  const avatar = new Avatar({
    container: stage,
    background: root.dataset.avatarBackground || undefined,
    onStatus: setStatus,
  });

  // Игрок создаётся после загрузки модели: он привязан к конкретному VRM.
  let player: ClipPlayer | null = null;
  let queue: DecodedClip[] = [];

  /** Прочитать скорость и паузу из полей страницы. */
  const readPlayerOptions = (): { speed: number; gapMs: number } => {
    const speed = speedInput ? Number.parseFloat(speedInput.value) : 1;
    const gapMs = gapInput ? Number.parseFloat(gapInput.value) : 0;
    return { speed: Number.isFinite(speed) ? speed : 1, gapMs: Number.isFinite(gapMs) ? gapMs : 0 };
  };

  const ensurePlayer = (): ClipPlayer | null => {
    const vrm = avatar.model;
    if (!vrm) {
      setClipStatus("Сначала загрузите модель (.vrm).");
      return null;
    }
    if (!player) {
      const { speed, gapMs } = readPlayerOptions();
      player = new ClipPlayer(vrm, {
        loop: false,
        speed,
        gapMs,
        onEnd: () => setClipStatus("Очередь проиграна."),
        onClip: (index) => setClipStatus(`Клип ${index + 1} из ${queue.length}…`),
      });
    }
    return player;
  };

  /** Загрузить очередь клипов в игрока (с пересозданием под новые скорость/паузу). */
  const loadQueue = (decoded: DecodedClip[], label: string): void => {
    queue = decoded;
    // Скорость и пауза могли измениться — пересоздаём игрок, чтобы он взял их.
    player?.dispose();
    player = null;
    const activePlayer = ensurePlayer();
    if (!activePlayer) return;
    activePlayer.loadQueue(decoded);
    const total = decoded.reduce((sum, clip) => sum + clip.frames / clip.fps, 0);
    setClipStatus(
      `${label}: ${decoded.length} клип(ов), ${decoded.reduce((n, c) => n + c.frames, 0)} кадров, ` +
        `${total.toFixed(2)} с. Нажмите «Играть».`,
    );
  };

  const initialUrl = root.dataset.avatarModelUrl?.trim();
  void avatar.load(initialUrl || undefined);

  form?.addEventListener("submit", (event: SubmitEvent) => {
    event.preventDefault();
    const url = urlInput?.value.trim();
    if (url) {
      // Новая модель — новый игрок, старый освобождаем.
      player?.dispose();
      player = null;
      queue = [];
      void avatar.load(url);
    }
  });

  demoButton?.addEventListener("click", async () => {
    setClipStatus("Сборка демо-клипа…");
    try {
      const payload = await encodeDemoClip();
      loadQueue([await decodeClipPayload(payload)], "Демо-клип");
    } catch (error) {
      setClipStatus(`Не удалось собрать клип: ${String(error)}`);
    }
  });

  queueButton?.addEventListener("click", async () => {
    setClipStatus("Сборка очереди демо-клипов…");
    try {
      const payloads = await encodeDemoQueue();
      const decoded = await Promise.all(payloads.map((payload) => decodeClipPayload(payload)));
      loadQueue(decoded, "Очередь демо-клипов (crossfade + нейтраль)");
      player?.start();
      if (player) setClipStatus("Очередь демо-клипов: воспроизведение…");
    } catch (error) {
      setClipStatus(`Не удалось собрать очередь: ${String(error)}`);
    }
  });

  playButton?.addEventListener("click", () => {
    if (queue.length === 0) {
      setClipStatus("Нет загруженной очереди.");
      return;
    }
    const activePlayer = ensurePlayer();
    if (!activePlayer) return;
    activePlayer.start();
    setClipStatus("Воспроизведение…");
  });

  stopButton?.addEventListener("click", () => {
    player?.stop();
    setClipStatus("Остановлено.");
  });

  fileInput?.addEventListener("change", async () => {
    const files = Array.from(fileInput.files ?? []);
    if (files.length === 0) return;
    try {
      const decoded = await Promise.all(
        files.map(async (file) => decodeClip(new Uint8Array(await file.arrayBuffer()))),
      );
      loadQueue(decoded, `Файлы: ${files.map((f) => f.name).join(", ")}`);
      player?.start();
    } catch (error) {
      setClipStatus(`Битый клип: ${String(error)}`);
    }
  });

  // Освобождаем WebGL при уходе со страницы (переход назад, закрытие вкладки).
  window.addEventListener(
    "pagehide",
    () => {
      player?.dispose();
      avatar.dispose();
    },
    { once: true },
  );
}

function init(): void {
  document.querySelectorAll<HTMLElement>("[data-avatar-page]").forEach(setupAvatarPage);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init, { once: true });
} else {
  init();
}
