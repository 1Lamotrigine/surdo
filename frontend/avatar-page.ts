/**
 * Точка входа тестовой страницы аватара (C1 + C3): `GET /avatar/`.
 * Создаёт `Avatar`, грузит VRM по адресу из поля, а затем может проиграть клип:
 * синтетический (машущие пальцы) или из файла `.json.gz`.
 */

import { Avatar, type AvatarStatus } from "./avatar";
import { decodeClip, decodeClipPayload, type DecodedClip } from "./clip";
import { ClipPlayer } from "./clip-player";
import { DACTYL_CROSSFADE_MS } from "./clip-queue";
import { DACTYL_ALPHABET, splitWord } from "./dactyl";
import {
  encodeDactylClip,
  encodeDemoClip,
  encodeDemoQueue,
  encodeNeutralPauseClip,
} from "./demo-clip";
import { DEMO_PHRASE, encodePhraseClips } from "./demo-phrase";
import {
  STUDENT_SETTINGS_DEFAULTS,
  StudentSettingsView,
  studentSettingsCss,
  studentThemeBackground,
  type StudentSettings,
} from "./student-settings";
import { SubtitleView, alignTokens, utteranceUnits, wordIndexForToken } from "./subtitles";

const STATUS_LABELS: Record<AvatarStatus, string> = {
  loading: "Загрузка…",
  ready: "Готово",
  error: "Ошибка",
};

/** Режим очереди: обычная фраза (C4) или склейка слова по буквам (C5). */
type QueueConfig = {
  mode: "phrase" | "dactyl";
  crossfadeMs?: number;
  label: string;
  /** Показать субтитры фразы и подсвечивать слова по текущему клипу (C6). */
  subtitles?: boolean;
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
  const dactylInput = root.querySelector<HTMLInputElement>("[data-avatar-dactyl-text]");
  const dactylButton = root.querySelector<HTMLButtonElement>("[data-avatar-dactyl]");
  const phraseButton = root.querySelector<HTMLButtonElement>("[data-avatar-phrase]");
  const subtitleRoot = root.querySelector<HTMLElement>("[data-avatar-subtitles]");
  const settingsRoot = root.querySelector<HTMLElement>("[data-avatar-settings]");
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

  // Субтитры (C6): подсвечивают слово по текущему клипу очереди.
  const subtitles = subtitleRoot ? new SubtitleView(subtitleRoot, { size: "large", theme: "dark" }) : null;
  // Соответствие «индекс клипа → слово субтитра» для текущей фразы.
  let phraseWordByClip: number[] = [];

  // Настройки студента (C7): скорость, размер, положение и фон аватара.
  let settingsView: StudentSettingsView | null = null;
  let lastSettingsSpeed = STUDENT_SETTINGS_DEFAULTS.speed;

  const applyStudentSettings = (settings: StudentSettings): void => {
    // Размер/сдвиг — CSS-переменные сцены (значения живут в CSS), фон — цвет
    // сцены Three.js, чтобы он совпадал с подложкой вокруг canvas.
    for (const [name, value] of Object.entries(studentSettingsCss(settings))) {
      stage.style.setProperty(name, value);
    }
    avatar.setBackground(studentThemeBackground(settings.theme));
    subtitles?.applyStyles({ size: "large", theme: settings.theme });
  };

  const highlightClip = (index: number): void => {
    const wordIndex = phraseWordByClip[index] ?? -1;
    subtitles?.highlight(wordIndex);
  };

  // Игрок создаётся после загрузки модели: он привязан к конкретному VRM.
  let player: ClipPlayer | null = null;
  let queue: DecodedClip[] = [];
  let queueConfig: QueueConfig = { mode: "phrase", label: "Очередь" };

  /** Прочитать скорость из настроек студента и паузу из поля страницы. */
  const readPlayerOptions = (): { speed: number; gapMs: number } => {
    const settingsSpeed = settingsView?.settings.speed;
    const fieldSpeed = speedInput ? Number.parseFloat(speedInput.value) : Number.NaN;
    const speed = settingsSpeed ?? (Number.isFinite(fieldSpeed) ? fieldSpeed : STUDENT_SETTINGS_DEFAULTS.speed);
    const gapMs = gapInput ? Number.parseFloat(gapInput.value) : 0;
    return { speed, gapMs: Number.isFinite(gapMs) ? gapMs : 0 };
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
        mode: queueConfig.mode,
        crossfadeMs: queueConfig.crossfadeMs,
        onEnd: () => {
          setClipStatus(`${queueConfig.label}: проиграно.`);
          subtitles?.highlight(-1);
        },
        onClip: (index) => {
          setClipStatus(`${queueConfig.label}: клип ${index + 1} из ${queue.length}…`);
          highlightClip(index);
        },
      });
    }
    return player;
  };

  /** Загрузить очередь клипов в игрока (с пересозданием под новые настройки). */
  const loadQueue = (decoded: DecodedClip[], config: QueueConfig): void => {
    queue = decoded;
    queueConfig = config;
    // Смена очереди без фразы снимает подсветку и старую разметку субтитров.
    if (!config.subtitles) {
      phraseWordByClip = [];
      subtitles?.clear();
    }
    // Режим/скорость/пауза могли измениться — пересоздаём игрок, чтобы он взял их.
    player?.dispose();
    player = null;
    const activePlayer = ensurePlayer();
    if (!activePlayer) return;
    activePlayer.loadQueue(decoded);
    const total = decoded.reduce((sum, clip) => sum + clip.frames / clip.fps, 0);
    setClipStatus(
      `${config.label}: ${decoded.length} клип(ов), ${decoded.reduce((n, c) => n + c.frames, 0)} кадров, ` +
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
      loadQueue([await decodeClipPayload(payload)], { mode: "phrase", label: "Демо-клип" });
    } catch (error) {
      setClipStatus(`Не удалось собрать клип: ${String(error)}`);
    }
  });

  queueButton?.addEventListener("click", async () => {
    setClipStatus("Сборка очереди демо-клипов…");
    try {
      const payloads = await encodeDemoQueue();
      const decoded = await Promise.all(payloads.map((payload) => decodeClipPayload(payload)));
      loadQueue(decoded, { mode: "phrase", label: "Очередь демо-клипов" });
      player?.start();
      if (player) setClipStatus("Очередь демо-клипов: воспроизведение…");
    } catch (error) {
      setClipStatus(`Не удалось собрать очередь: ${String(error)}`);
    }
  });

  dactylButton?.addEventListener("click", async () => {
    const text = dactylInput?.value.trim() ?? "";
    if (!text) {
      setClipStatus("Введите слово для дактиля.");
      return;
    }
    setClipStatus("Сборка дактиля…");
    try {
      const chars = splitWord(text);
      if (chars.length === 0) {
        setClipStatus("Нет букв для дактиля (только кириллица и цифры).");
        return;
      }
      // На каждый знак — клип: буква/цифра из синтетической азбуки, пробел —
      // короткий клип нейтральной позы (пауза между словами).
      const decoded = await Promise.all(
        chars.map(async (char) =>
          decodeClipPayload(
            char.kind === "space"
              ? await encodeNeutralPauseClip()
              : await encodeDactylClip(char.char, DACTYL_ALPHABET),
          ),
        ),
      );
      const letters = chars.filter((c) => c.kind !== "space").length;
      loadQueue(decoded, {
        mode: "dactyl",
        crossfadeMs: DACTYL_CROSSFADE_MS,
        label: `Дактиль «${text}» (${letters} букв)`,
      });
      player?.start();
      if (player) setClipStatus(`Дактиль «${text}»: воспроизведение по буквам…`);
    } catch (error) {
      setClipStatus(`Не удалось собрать дактиль: ${String(error)}`);
    }
  });

  phraseButton?.addEventListener("click", async () => {
    setClipStatus("Сборка фразы с субтитрами…");
    try {
      const payloads = await encodePhraseClips(DEMO_PHRASE);
      const decoded = await Promise.all(payloads.map((payload) => decodeClipPayload(payload)));
      // Разметка субтитра и карта «индекс клипа → слово»: единица показа знает
      // свой токен, токен — своё слово в тексте (FR-10).
      const words = alignTokens(DEMO_PHRASE);
      const units = utteranceUnits(DEMO_PHRASE);
      phraseWordByClip = units.map((unit) => wordIndexForToken(words, unit.tokenIndex));
      subtitles?.render(DEMO_PHRASE, words);
      loadQueue(decoded, {
        mode: "phrase",
        label: `Фраза «${DEMO_PHRASE.text}»`,
        subtitles: true,
      });
      player?.start();
      if (player) setClipStatus(`Фраза «${DEMO_PHRASE.text}»: субтитры подсвечивают слово…`);
    } catch (error) {
      setClipStatus(`Не удалось собрать фразу: ${String(error)}`);
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
      loadQueue(decoded, { mode: "phrase", label: `Файлы: ${files.map((f) => f.name).join(", ")}` });
      player?.start();
    } catch (error) {
      setClipStatus(`Битый клип: ${String(error)}`);
    }
  });

  // Настройки студента (C7) применяются сразу и переживают перезагрузку страницы.
  if (settingsRoot) {
    settingsView = new StudentSettingsView(settingsRoot, {
      onChange: (settings) => {
        applyStudentSettings(settings);
        if (settings.speed === lastSettingsSpeed) return;
        lastSettingsSpeed = settings.speed;
        // Скорость входит в план очереди C4: игрок пересобирает его на ходу,
        // сохраняя текущий клип и кадр (если он уже создан).
        player?.setSpeed(settings.speed);
        if (queue.length > 0) setClipStatus(`Скорость ${settings.speed.toFixed(2)}x.`);
      },
    });
  }

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
