/**
 * Точка входа тестовой страницы аватара (C1 + C3): `GET /avatar/`.
 * Создаёт `Avatar`, грузит VRM по адресу из поля, а затем может проиграть клип:
 * синтетический (машущие пальцы) или из файла `.json.gz`.
 */

import { Avatar, type AvatarStatus } from "./avatar";
import { decodeClip, decodeClipPayload, type DecodedClip } from "./clip";
import { ClipPlayer } from "./clip-player";
import { encodeDemoClip } from "./demo-clip";

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
  const playButton = root.querySelector<HTMLButtonElement>("[data-avatar-play]");
  const stopButton = root.querySelector<HTMLButtonElement>("[data-avatar-stop]");
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
  let clip: DecodedClip | null = null;

  const ensurePlayer = (): ClipPlayer | null => {
    const vrm = avatar.model;
    if (!vrm) {
      setClipStatus("Сначала загрузите модель (.vrm).");
      return null;
    }
    if (!player) {
      player = new ClipPlayer(vrm, {
        loop: true,
        speed: 1,
        onEnd: () => setClipStatus("Клип проигран."),
      });
    }
    return player;
  };

  const loadClip = async (decoded: DecodedClip, label: string): Promise<void> => {
    const activePlayer = ensurePlayer();
    if (!activePlayer) return;
    clip = decoded;
    activePlayer.load(decoded);
    setClipStatus(`${label}: ${decoded.frames} кадров, ${decoded.fps} fps.`);
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
      clip = null;
      void avatar.load(url);
    }
  });

  demoButton?.addEventListener("click", async () => {
    setClipStatus("Сборка демо-клипа…");
    try {
      const payload = await encodeDemoClip();
      await loadClip(await decodeClipPayload(payload), "Демо-клип");
    } catch (error) {
      setClipStatus(`Не удалось собрать клип: ${String(error)}`);
    }
  });

  playButton?.addEventListener("click", () => {
    if (!clip) {
      setClipStatus("Нет загруженного клипа.");
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
    const file = fileInput.files?.[0];
    if (!file) return;
    try {
      const decoded = await decodeClip(new Uint8Array(await file.arrayBuffer()));
      await loadClip(decoded, `Файл ${file.name}`);
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
