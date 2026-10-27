/**
 * Инструмент записи жестов (D1–D3): камера, скелет MediaPipe, запись, обрезка,
 * упаковка клипа, предпросмотр на аватаре и сохранение черновика.
 *
 * Страница `GET /dictionary/record/` открывает камеру по кнопке и рисует поверх
 * видео позу, лицо и кисти. По кнопке «Начать запись» кадры складываются с
 * метками времени; после остановки пустые края обрезаются, кадры пересобираются
 * на 30 FPS, сглаживаются One Euro и упаковываются в `.json.gz`. Полученный
 * файл сразу распаковывается обратно — это проверка обратимости формата. D3
 * добавляет аватар и форму метаданных: жест уходит в API черновиком.
 */

import { Avatar } from "./avatar";
import { decodeClip, type DecodedClip } from "./clip";
import { ClipPlayer } from "./clip-player";
import {
  autoTrimRange,
  clampTrimRange,
  encodeRecordedClip,
  type CapturedFrame,
  type TrimRange,
} from "./clip-record";
import {
  HolisticDetector,
  framePointCount,
  handsDetected,
} from "./holistic";
import {
  SIGN_LANGUAGES,
  submitSignDraft,
  validateSignDraft,
} from "./sign-draft";
import { drawSkeleton, type HolisticFrame, type Viewport } from "./skeleton";

type StatusState = "idle" | "loading" | "running" | "warning" | "error";

const STATUS_LABELS: Record<StatusState, string> = {
  idle: "Камера выключена",
  loading: "Включение камеры…",
  running: "Камера работает",
  warning: "Камера работает, но скелет недоступен",
  error: "Ошибка камеры",
};

const CLIP_GLOSS = "ЗАПИСЬ";

function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}

function positiveNumber(value: string | undefined, fallback: number): number {
  const parsed = Number.parseFloat(value ?? "");
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function formatSeconds(ms: number): string {
  return `${(ms / 1000).toFixed(2)} с`;
}

function formatSize(bytes: number): string {
  return bytes >= 1024 * 1024
    ? `${(bytes / (1024 * 1024)).toFixed(2)} МБ`
    : `${Math.max(1, Math.round(bytes / 1024))} КБ`;
}

function setupRecordPage(root: HTMLElement): void {
  const stage = root.querySelector<HTMLElement>("[data-record-stage]");
  const video = root.querySelector<HTMLVideoElement>("[data-record-video]");
  const canvas = root.querySelector<HTMLCanvasElement>("[data-record-canvas]");
  const startButton = root.querySelector<HTMLButtonElement>("[data-record-start]");
  const stopButton = root.querySelector<HTMLButtonElement>("[data-record-stop]");
  const recordStartButton = root.querySelector<HTMLButtonElement>("[data-record-start-clip]");
  const recordStopButton = root.querySelector<HTMLButtonElement>("[data-record-stop-clip]");
  const status = root.querySelector<HTMLElement>("[data-record-status]");
  const clipStatus = root.querySelector<HTMLElement>("[data-record-clip-status]");
  const timer = root.querySelector<HTMLElement>("[data-record-timer]");
  const stats = root.querySelector<HTMLElement>("[data-record-stats]");
  const hands = root.querySelector<HTMLElement>("[data-record-hands]");
  const trimSection = root.querySelector<HTMLElement>("[data-record-trim]");
  const trimStart = root.querySelector<HTMLInputElement>("[data-record-trim-start]");
  const trimEnd = root.querySelector<HTMLInputElement>("[data-record-trim-end]");
  const trimStartValue = root.querySelector<HTMLElement>("[data-record-trim-start-value]");
  const trimEndValue = root.querySelector<HTMLElement>("[data-record-trim-end-value]");
  const buildStatus = root.querySelector<HTMLElement>("[data-record-build-status]");
  const download = root.querySelector<HTMLAnchorElement>("[data-record-download]");
  const previewSection = root.querySelector<HTMLElement>("[data-record-preview]");
  const previewStage = root.querySelector<HTMLElement>("[data-record-preview-stage]");
  const previewPlaceholder = root.querySelector<HTMLElement>("[data-record-preview-placeholder]");
  const previewStatus = root.querySelector<HTMLElement>("[data-record-preview-status]");
  const previewPlay = root.querySelector<HTMLButtonElement>("[data-record-preview-play]");
  const previewStop = root.querySelector<HTMLButtonElement>("[data-record-preview-stop]");
  const signForm = root.querySelector<HTMLFormElement>("[data-sign-form]");
  const signGloss = root.querySelector<HTMLInputElement>("[data-sign-gloss]");
  const signLang = root.querySelector<HTMLSelectElement>("[data-sign-lang]");
  const signDescription = root.querySelector<HTMLTextAreaElement>("[data-sign-description]");
  const signSave = root.querySelector<HTMLButtonElement>("[data-sign-save]");
  const signStatus = root.querySelector<HTMLElement>("[data-sign-status]");
  const signAdmin = root.querySelector<HTMLAnchorElement>("[data-sign-admin]");
  if (!video || !canvas) return;

  const context = canvas.getContext("2d");
  const wasmBasePath = root.dataset.mediapipeWasm?.trim() ?? "";
  const modelUrl = root.dataset.mediapipeModelUrl?.trim() ?? "";
  const avatarModelUrl = root.dataset.avatarModelUrl?.trim() ?? "";
  const fps = positiveNumber(root.dataset.recordFps, 30);
  const maxFrames = Math.max(1, Math.round(positiveNumber(root.dataset.recordMaxFrames, 300)));
  const maxBytes = Math.max(1, positiveNumber(root.dataset.recordMaxBytes, 2 * 1024 * 1024));
  const maxDurationMs = (maxFrames / fps) * 1000;
  const captureIntervalMs = 1000 / fps;

  let stream: MediaStream | null = null;
  let detector: HolisticDetector | null = null;
  let detectorPromise: Promise<HolisticDetector | null> | null = null;
  let animationFrame = 0;
  let cameraStarting = false;
  let lastVideoTime = -1;
  let lastTimestamp = 0;
  let lastFrame: HolisticFrame | null = null;
  let lastStatsAt = 0;
  let detectTimes: number[] = [];
  let detectError: string | null = null;
  let disposed = false;

  // Запись и обрезка (D2).
  let recording = false;
  let recordingStartedAt = 0;
  let lastCaptureAt = -1;
  let recordingFrames: CapturedFrame[] = [];
  let recordedFrames: CapturedFrame[] = [];
  let trimRange: TrimRange | null = null;
  let rebuildTimer = 0;
  let buildToken = 0;
  let downloadUrl: string | null = null;
  let currentFile: Uint8Array | null = null;
  let currentClipFrames = 0;
  let clipBuilding = false;
  let clipOversize = false;

  // Предпросмотр на аватаре (D3): модель грузится лениво, только после клипа.
  let previewAvatar: Avatar | null = null;
  let previewPlayer: ClipPlayer | null = null;
  let previewAvatarPromise: Promise<Avatar | null> | null = null;
  let previewClip: DecodedClip | null = null;
  let previewToken = 0;
  let previewReady = false;

  // Сохранение черновика (D3): после успеха дубликат не отправляем.
  let savedSignId: number | null = null;
  let savingDraft = false;

  const setStatus = (state: StatusState, detail?: string): void => {
    if (!status) return;
    status.dataset.state = state;
    status.textContent = detail ? `${STATUS_LABELS[state]}: ${detail}` : STATUS_LABELS[state];
  };

  const setClipStatus = (state: StatusState, text: string): void => {
    if (!clipStatus) return;
    clipStatus.dataset.state = state;
    clipStatus.textContent = text;
  };

  const setBuildStatus = (state: StatusState, text: string): void => {
    if (!buildStatus) return;
    buildStatus.dataset.state = state;
    buildStatus.textContent = text;
  };

  const setPreviewStatus = (state: StatusState, text: string): void => {
    if (!previewStatus) return;
    previewStatus.dataset.state = state;
    previewStatus.textContent = text;
  };

  const setSignStatus = (state: StatusState, text: string): void => {
    if (!signStatus) return;
    signStatus.dataset.state = state;
    signStatus.textContent = text;
  };

  const updatePreviewButtons = (): void => {
    if (previewPlay) previewPlay.disabled = !previewReady;
    if (previewStop) previewStop.disabled = !previewReady;
  };

  const updateSaveButton = (): void => {
    if (!signSave) return;
    const canSave =
      currentFile !== null &&
      !clipBuilding &&
      !clipOversize &&
      savedSignId === null &&
      !savingDraft;
    signSave.disabled = !canSave;
    signSave.textContent =
      savedSignId !== null
        ? "Черновик сохранён"
        : savingDraft
          ? "Сохранение…"
          : "Сохранить черновик";
  };

  const setDraftFieldsDisabled = (disabled: boolean): void => {
    signForm
      ?.querySelectorAll<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>(
        'input:not([type="hidden"]), select, textarea',
      )
      .forEach((field) => {
        field.disabled = disabled;
      });
  };

  const clearSavedDraft = (): void => {
    savedSignId = null;
    setDraftFieldsDisabled(false);
    if (signAdmin) signAdmin.hidden = true;
    updateSaveButton();
  };

  const updateButtons = (): void => {
    const cameraOn = stream !== null;
    if (startButton) startButton.disabled = cameraOn || cameraStarting;
    if (stopButton) stopButton.disabled = !cameraOn;
    if (recordStartButton) {
      recordStartButton.disabled = !cameraOn || detector === null || recording;
    }
    if (recordStopButton) recordStopButton.disabled = !recording;
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

  const revokeDownload = (): void => {
    if (downloadUrl) {
      URL.revokeObjectURL(downloadUrl);
      downloadUrl = null;
    }
    if (download) {
      download.hidden = true;
      download.removeAttribute("href");
    }
  };

  const frameTime = (index: number): number => {
    if (recordedFrames.length === 0) return 0;
    return Math.max(0, recordedFrames[index].timeMs - recordedFrames[0].timeMs);
  };

  const updateTrimLabels = (): void => {
    if (!trimRange) return;
    const last = Math.max(trimRange.start, trimRange.end - 1);
    if (trimStartValue) trimStartValue.textContent = formatSeconds(frameTime(trimRange.start));
    if (trimEndValue) trimEndValue.textContent = formatSeconds(frameTime(last));
  };

  const scheduleRebuild = (): void => {
    if (rebuildTimer) window.clearTimeout(rebuildTimer);
    rebuildTimer = window.setTimeout(() => {
      rebuildTimer = 0;
      void rebuildClip();
    }, 120);
  };

  const resetPreview = (): void => {
    previewToken += 1;
    previewClip = null;
    previewReady = false;
    previewPlayer?.stop();
    previewAvatar?.setNeutralPose();
    updatePreviewButtons();
  };

  const ensurePreviewAvatar = (): Promise<Avatar | null> => {
    if (!previewStage) return Promise.resolve(null);
    if (!avatarModelUrl) {
      setPreviewStatus(
        "warning",
        "Модель аватара не задана (AVATAR_MODEL_URL): предпросмотр недоступен, но клип можно сохранить.",
      );
      return Promise.resolve(null);
    }
    if (previewAvatar) return Promise.resolve(previewAvatar);
    if (previewAvatarPromise) return previewAvatarPromise;

    previewAvatarPromise = (async () => {
      try {
        previewPlaceholder?.remove();
        const created = new Avatar({
          container: previewStage,
          onStatus: (state, detail) => {
            if (state === "loading") {
              setPreviewStatus("loading", detail ?? "Загрузка модели аватара…");
            } else if (state === "error") {
              setPreviewStatus(
                "warning",
                `Модель не загружена: ${detail ?? "неизвестная ошибка"}. Клип можно сохранить.`,
              );
            }
          },
        });
        previewAvatar = created;
        await created.load(avatarModelUrl);
        return created;
      } catch (error) {
        setPreviewStatus(
          "warning",
          `Предпросмотр недоступен: ${errorMessage(error)}. Клип можно сохранить.`,
        );
        return null;
      } finally {
        previewAvatarPromise = null;
      }
    })();
    return previewAvatarPromise;
  };

  const syncPreview = (): void => {
    if (!previewAvatar?.model || !previewClip) {
      previewReady = false;
      updatePreviewButtons();
      return;
    }
    if (!previewPlayer) {
      previewPlayer = new ClipPlayer(previewAvatar.model, {
        smoothing: false,
        loop: false,
        onEnd: () => {
          setPreviewStatus("running", "Клип проигран. Нажмите «Играть», чтобы повторить.");
        },
      });
    }
    previewPlayer.load(previewClip);
    previewReady = true;
    updatePreviewButtons();
    setPreviewStatus(
      "running",
      `Клип загружен на аватар: ${previewClip.frames} кадров, ` +
        `${formatSeconds((previewClip.frames / previewClip.fps) * 1000)}. Нажмите «Играть».`,
    );
  };

  const setPreviewClip = async (clip: DecodedClip | null): Promise<void> => {
    previewClip = clip;
    previewReady = false;
    updatePreviewButtons();
    if (!clip) {
      setPreviewStatus("idle", "Клип ещё не собран.");
      return;
    }
    if (!previewStage) return;
    if (!avatarModelUrl) {
      setPreviewStatus(
        "warning",
        "Модель аватара не задана: предпросмотр недоступен, но клип можно сохранить.",
      );
      return;
    }

    const token = ++previewToken;
    setPreviewStatus("loading", "Клип готов. Загрузка модели аватара…");
    const created = await ensurePreviewAvatar();
    if (token !== previewToken) return;
    if (!created?.model) {
      previewReady = false;
      updatePreviewButtons();
      return;
    }
    try {
      syncPreview();
    } catch (error) {
      previewReady = false;
      updatePreviewButtons();
      setPreviewStatus(
        "warning",
        `Предпросмотр не запустился: ${errorMessage(error)}. Клип можно сохранить.`,
      );
    }
  };

  const draftLanguages = signLang
    ? Array.from(signLang.options)
        .map((option) => option.value)
        .filter((value) => value.length > 0)
    : [];
  const allowedLanguages = draftLanguages.length > 0 ? draftLanguages : SIGN_LANGUAGES;

  const handleSignSubmit = async (event: SubmitEvent): Promise<void> => {
    event.preventDefault();
    const file = currentFile;
    if (!file) {
      setSignStatus("error", "Сначала запишите и соберите клип.");
      return;
    }
    if (savedSignId !== null || savingDraft) return;

    const validation = validateSignDraft(
      {
        gloss: signGloss?.value ?? "",
        lang: signLang?.value ?? "rsl",
        description: signDescription?.value ?? "",
      },
      allowedLanguages,
    );
    if (!validation.valid) {
      const messages = Object.values(validation.errors).filter(
        (value): value is string => typeof value === "string",
      );
      setSignStatus("error", messages.join(" "));
      return;
    }
    if (signGloss) signGloss.value = validation.draft.gloss;
    if (signDescription) signDescription.value = validation.draft.description;

    const csrf =
      signForm?.querySelector<HTMLInputElement>('input[name="csrfmiddlewaretoken"]')?.value ?? "";
    if (!csrf) {
      setSignStatus("error", "Не найден CSRF-токен формы. Обновите страницу.");
      return;
    }

    savingDraft = true;
    updateSaveButton();
    setSignStatus("loading", "Сохранение черновика…");
    try {
      const payload = await submitSignDraft({
        url: signForm?.dataset.signApiUrl || "/api/signs/",
        csrfToken: csrf,
        draft: validation.draft,
        file: new Blob([file as BlobPart], { type: "application/gzip" }),
        filename: `zapis-${currentClipFrames}f.json.gz`,
      });
      savedSignId = payload.id;
      setDraftFieldsDisabled(true);
      if (signAdmin) signAdmin.hidden = false;
      setSignStatus(
        "running",
        `Черновик №${payload.id} «${payload.gloss}» сохранён. Он появится в Django Admin.`,
      );
    } catch (error) {
      setSignStatus("error", `Не удалось сохранить: ${errorMessage(error)}`);
    } finally {
      savingDraft = false;
      updateSaveButton();
    }
  };

  const rebuildClip = async (): Promise<void> => {
    if (!trimRange || recordedFrames.length === 0) return;
    const token = ++buildToken;
    clipBuilding = true;
    currentFile = null;
    currentClipFrames = 0;
    clipOversize = false;
    clearSavedDraft();
    resetPreview();
    revokeDownload();
    updateSaveButton();
    setSignStatus("loading", "Сборка клипа…");
    setBuildStatus("loading", "Сборка клипа: Float16, gzip и проверка распаковкой…");

    try {
      const result = await encodeRecordedClip({
        frames: recordedFrames,
        range: trimRange,
        fps,
        maxFrames,
        gloss: CLIP_GLOSS,
      });
      if (token !== buildToken) return;

      // Контрольная распаковка тем же декодером, что и у аватара (C2).
      const decoded = await decodeClip(result.file);
      if (decoded.frames !== result.frameCount) {
        throw new Error(`распаковка дала ${decoded.frames} кадров вместо ${result.frameCount}.`);
      }
      if (token !== buildToken) return;

      currentFile = result.file;
      currentClipFrames = result.frameCount;
      clipOversize = result.file.byteLength > maxBytes;

      downloadUrl = URL.createObjectURL(
        new Blob([result.file as BlobPart], { type: "application/gzip" }),
      );
      if (download) {
        download.href = downloadUrl;
        download.download = `zapis-${result.frameCount}f.json.gz`;
        download.hidden = false;
      }
      if (previewSection) previewSection.hidden = false;

      const summary =
        `${result.frameCount} кадров, ${formatSeconds(result.durationMs)}, ` +
        `${formatSize(result.file.byteLength)}.`;
      const verified = `Распаковка: формат v${decoded.version}, ${decoded.points} точек — совпадает.`;
      if (clipOversize) {
        setBuildStatus(
          "warning",
          `${summary} ${verified} Файл больше лимита ${formatSize(maxBytes)}: сократите жест.`,
        );
        setSignStatus(
          "warning",
          `Клип больше лимита ${formatSize(maxBytes)}: уменьшите длительность, чтобы сохранить.`,
        );
      } else {
        setBuildStatus("running", `${summary} ${verified}`);
        setSignStatus("idle", "Клип готов. Заполните метаданные и сохраните черновик.");
      }

      void setPreviewClip(decoded);
    } catch (error) {
      if (token === buildToken) {
        currentFile = null;
        currentClipFrames = 0;
        clipOversize = false;
        setBuildStatus("error", `Не удалось собрать клип: ${errorMessage(error)}`);
        setSignStatus("error", "Клип не собран — сохранить черновик нельзя.");
      }
    } finally {
      if (token === buildToken) {
        clipBuilding = false;
        updateSaveButton();
      }
    }
  };

  const configureTrim = (range: TrimRange): void => {
    if (recordedFrames.length === 0) return;
    const lastIndex = recordedFrames.length - 1;
    if (trimStart) {
      trimStart.min = "0";
      trimStart.max = String(lastIndex);
      trimStart.value = String(Math.min(range.start, lastIndex));
    }
    if (trimEnd) {
      trimEnd.min = "0";
      trimEnd.max = String(lastIndex);
      trimEnd.value = String(Math.min(range.end - 1, lastIndex));
    }
    if (trimSection) trimSection.hidden = false;
    updateTrimLabels();
  };

  const onTrimInput = (): void => {
    if (!trimStart || !trimEnd || recordedFrames.length === 0) return;
    const lastIndex = recordedFrames.length - 1;
    const minFrames = Math.min(2, recordedFrames.length);
    let start = Math.max(0, Math.min(Math.round(Number(trimStart.value)), lastIndex));
    let end = Math.max(0, Math.min(Math.round(Number(trimEnd.value)), lastIndex));

    // Ползунки не пересекаются: двигаем тот, который сейчас не меняют.
    if (end - start + 1 < minFrames) {
      if (document.activeElement === trimStart) end = Math.min(lastIndex, start + minFrames - 1);
      else start = Math.max(0, end - minFrames + 1);
    }
    trimStart.value = String(start);
    trimEnd.value = String(end);
    trimRange = clampTrimRange({ start, end: end + 1 }, recordedFrames.length, minFrames);
    updateTrimLabels();
    scheduleRebuild();
  };

  const finishRecording = async (reason: "stop" | "limit"): Promise<void> => {
    if (!recording) return;
    recording = false;
    updateButtons();
    const frames = recordingFrames;
    recordingFrames = [];
    if (timer) {
      timer.textContent = `${frames.length} кадров · ${formatSeconds(
        Math.max(0, (frames[frames.length - 1]?.timeMs ?? 0) - (frames[0]?.timeMs ?? 0)),
      )}`;
    }

    if (frames.length === 0) {
      setClipStatus("error", "Кадров не записано: включите камеру и начните заново.");
      setSignStatus("error", "Нет записи — сохранить черновик нельзя.");
      return;
    }

    recordedFrames = frames;
    const range = autoTrimRange(frames);
    if (!range) {
      trimRange = null;
      if (trimSection) trimSection.hidden = true;
      if (previewSection) previewSection.hidden = true;
      setClipStatus(
        "error",
        "В записи не было позы или кистей. Встаньте в кадр целиком и повторите.",
      );
      setSignStatus("error", "Клип не собран — сохранить черновик нельзя.");
      return;
    }

    trimRange = range;
    configureTrim(range);
    setClipStatus(
      reason === "limit" ? "warning" : "running",
      reason === "limit"
        ? `Запись остановлена по лимиту ${formatSeconds(maxDurationMs)}.`
        : `Запись остановлена: ${frames.length} кадров. Края обрезаны автоматически.`,
    );
    await rebuildClip();
  };

  const startRecording = (): void => {
    if (!stream || !detector || recording) return;
    if (rebuildTimer) {
      window.clearTimeout(rebuildTimer);
      rebuildTimer = 0;
    }
    buildToken += 1;
    clipBuilding = false;
    currentFile = null;
    currentClipFrames = 0;
    clipOversize = false;
    clearSavedDraft();
    resetPreview();
    revokeDownload();
    recordedFrames = [];
    recordingFrames = [];
    trimRange = null;
    if (trimSection) trimSection.hidden = true;
    if (previewSection) previewSection.hidden = true;
    setBuildStatus("idle", "Клип ещё не собран.");
    setSignStatus("idle", "Сначала запишите и соберите клип.");
    updateSaveButton();
    recording = true;
    recordingStartedAt = performance.now();
    lastCaptureAt = -1;
    if (timer) timer.textContent = `0.00 с / ${formatSeconds(maxDurationMs)}`;
    setClipStatus("running", `Идёт запись, максимум ${formatSeconds(maxDurationMs)}.`);
    updateButtons();
  };

  const captureFrame = (now: number): void => {
    if (!recording || !lastFrame) return;
    if (lastCaptureAt >= 0 && now - lastCaptureAt < captureIntervalMs - 1) return;
    lastCaptureAt = now;
    recordingFrames.push({ timeMs: now, frame: lastFrame });
  };

  const updateTimer = (now: number): void => {
    if (!recording) return;
    const elapsed = now - recordingStartedAt;
    if (timer) {
      timer.textContent = `${formatSeconds(elapsed)} / ${formatSeconds(maxDurationMs)} · ${recordingFrames.length} кадров`;
    }
    if (elapsed >= maxDurationMs) void finishRecording("limit");
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
        captureFrame(now);
        render();
      } catch (error) {
        // Один сбой не должен ронять предпросмотр камеры: показываем причину и
        // отключаем детектор до повторного запуска.
        detectError = errorMessage(error);
        detector.dispose();
        detector = null;
        lastFrame = null;
        setStatus("warning", `сбой MediaPipe: ${detectError}`);
        updateButtons();
      }
    }
    updateStats(now);
    updateTimer(now);
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
        updateButtons();
        return detector;
      } catch (error) {
        detectError = errorMessage(error);
        if (stream) setStatus("warning", detectError);
        updateButtons();
        return null;
      } finally {
        detectorPromise = null;
      }
    })();
    return detectorPromise;
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

  const stopCamera = (finalize = true): void => {
    if (recording) {
      if (finalize) void finishRecording("stop");
      else {
        recording = false;
        recordingFrames = [];
      }
    }
    stopLoop();
    stream?.getTracks().forEach((track) => track.stop());
    stream = null;
    video.srcObject = null;
    stage?.classList.remove("is-live");
    clearCanvas();
    cameraStarting = false;
    updateButtons();
    setStatus("idle");
    if (stats) stats.textContent = "Скелет не подключён";
    if (hands) hands.textContent = "Кисти: —";
  };

  const startCamera = async (): Promise<void> => {
    if (stream || cameraStarting) return;
    cameraStarting = true;
    updateButtons();
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
      cameraStarting = false;
      stage?.classList.add("is-live");
      render();
      setStatus("running");
      updateButtons();
      // Модель грузится параллельно: видео появляется сразу, скелет — как только
      // будет готов WASM. Ошибка модели не мешает смотреть камеру.
      void loadDetector().then((loaded) => {
        if (loaded && stream) setStatus("running");
      });
      animationFrame = requestAnimationFrame(loop);
    } catch (error) {
      cameraStarting = false;
      stopCamera();
      setStatus("error", errorMessage(error));
    }
  };

  startButton?.addEventListener("click", () => {
    void startCamera();
  });
  stopButton?.addEventListener("click", () => stopCamera());
  recordStartButton?.addEventListener("click", startRecording);
  recordStopButton?.addEventListener("click", () => void finishRecording("stop"));
  trimStart?.addEventListener("input", onTrimInput);
  trimEnd?.addEventListener("input", onTrimInput);

  previewPlay?.addEventListener("click", () => {
    if (!previewReady || !previewPlayer) return;
    previewPlayer.start();
    setPreviewStatus("running", "Воспроизведение клипа на аватаре…");
  });
  previewStop?.addEventListener("click", () => {
    previewPlayer?.stop();
    previewAvatar?.setNeutralPose();
    setPreviewStatus("idle", "Остановлено. Можно сыграть ещё раз.");
  });
  signForm?.addEventListener("submit", (event) => {
    void handleSignSubmit(event);
  });

  // Поворот телефона или изменение размера окна: холст должен совпасть с видео.
  window.addEventListener("resize", render);

  window.addEventListener(
    "pagehide",
    () => {
      disposed = true;
      if (rebuildTimer) window.clearTimeout(rebuildTimer);
      buildToken += 1;
      stopCamera(false);
      revokeDownload();
      previewPlayer?.dispose();
      previewPlayer = null;
      previewAvatar?.dispose();
      previewAvatar = null;
      detector?.dispose();
      detector = null;
      window.removeEventListener("resize", render);
    },
    { once: true },
  );

  updateButtons();
  updatePreviewButtons();
  updateSaveButton();
  setBuildStatus("idle", "Клип ещё не собран.");
  setPreviewStatus("idle", "Клип ещё не собран.");
  setSignStatus("idle", "Сначала запишите и соберите клип.");
  if (timer) timer.textContent = `0.00 с / ${formatSeconds(maxDurationMs)}`;
}

function init(): void {
  document.querySelectorAll<HTMLElement>("[data-record-page]").forEach(setupRecordPage);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init, { once: true });
} else {
  init();
}
