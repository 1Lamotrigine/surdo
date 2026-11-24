import type { HolisticDetector } from "./holistic";
import type { SignReference, signFeatures } from "./sign-recognition";

const SAMPLE_INTERVAL_MS = 65;
const RECORDING_LIMIT_MS = 5_000;

export function setupStudentSign(root: HTMLElement): (() => void) | null {
  const panel = root.querySelector<HTMLElement>("[data-sign-panel]");
  const modes = root.querySelector<HTMLElement>("[data-sign-modes]");
  const receive = modes?.querySelector<HTMLButtonElement>("[data-sign-receive]");
  const send = modes?.querySelector<HTMLButtonElement>("[data-sign-send]");
  const video = panel?.querySelector<HTMLVideoElement>("[data-sign-video]");
  const start = panel?.querySelector<HTMLButtonElement>("[data-sign-start]");
  const finish = panel?.querySelector<HTMLButtonElement>("[data-sign-finish]");
  const cancel = panel?.querySelector<HTMLButtonElement>("[data-sign-cancel]");
  const status = panel?.querySelector<HTMLElement>("[data-sign-status]");
  const draft = panel?.querySelector<HTMLTextAreaElement>("[data-sign-draft]");
  const toChat = panel?.querySelector<HTMLButtonElement>("[data-sign-to-chat]");
  const speak = panel?.querySelector<HTMLButtonElement>("[data-sign-speak]");
  const chat = root.querySelector<HTMLTextAreaElement>("[data-chat-input]");
  if (!panel || !modes || !receive || !send || !video || !start || !finish || !cancel ||
      !status || !draft || !toChat || !speak || !chat) return null;

  const receiving = root.querySelectorAll<HTMLElement>("[data-receive-panel]");
  let session: AbortController | null = null;
  let stream: MediaStream | null = null;
  let detector: HolisticDetector | null = null;
  let references: SignReference[] | null = null;
  let timer = 0;
  let complete: (() => void) | null = null;
  let speaking: SpeechSynthesisUtterance | null = null;
  const speech = window.speechSynthesis;
  speak.hidden = !speech || !("SpeechSynthesisUtterance" in window);

  const stopCapture = (): void => {
    session?.abort();
    session = null;
    window.clearInterval(timer);
    stream?.getTracks().forEach((track) => track.stop());
    stream = null;
    video.srcObject = null;
    video.hidden = true;
    start.disabled = false;
    finish.hidden = true;
    cancel.hidden = true;
    complete = null;
  };

  const stopSpeech = (): void => {
    if (speaking) speech.cancel();
    speaking = null;
  };

  const setMode = (signing: boolean): void => {
    receive.setAttribute("aria-pressed", String(!signing));
    send.setAttribute("aria-pressed", String(signing));
    receiving.forEach((section) => { section.hidden = signing; });
    panel.hidden = !signing;
    if (!signing) {
      stopCapture();
      detector?.dispose();
      detector = null;
      stopSpeech();
      status.textContent = "";
    }
  };

  const syncDraft = (): void => {
    toChat.disabled = speak.disabled = !draft.value.trim();
  };

  receive.addEventListener("click", () => setMode(false));
  send.addEventListener("click", () => { setMode(true); if (!session) start.click(); });
  draft.addEventListener("input", syncDraft);
  toChat.addEventListener("click", () => {
    const previous = chat.value;
    chat.value = draft.value.trim();
    chat.form?.requestSubmit();
    if (!chat.value) {
      draft.value = "";
      syncDraft();
      status.textContent = "Сообщение передано в чат.";
    } else {
      status.textContent = "Нет соединения с чатом. Повторите отправку.";
    }
    chat.value = previous;
  });

  speak.addEventListener("click", () => {
    stopSpeech();
    const utterance = new SpeechSynthesisUtterance(draft.value.trim());
    utterance.lang = "ru-RU";
    utterance.voice = speech.getVoices().find((voice) => /^ru\b/i.test(voice.lang)) ?? null;
    utterance.onend = () => { if (speaking === utterance) speaking = null; };
    utterance.onerror = () => {
      if (speaking !== utterance) return;
      speaking = null;
      status.textContent = "Браузер не смог озвучить текст.";
    };
    speaking = utterance;
    speech.speak(utterance);
  });

  cancel.addEventListener("click", () => {
    stopCapture();
    status.textContent = "Запись отменена.";
  });
  finish.addEventListener("click", () => complete?.());

  start.addEventListener("click", async () => {
    if (session) return;
    if (!navigator.mediaDevices?.getUserMedia) {
      status.textContent = "Камера доступна на HTTPS или localhost в поддерживаемом браузере.";
      return;
    }

    const controller = new AbortController();
    const { signal } = controller;
    session = controller;
    start.disabled = true;
    cancel.hidden = false;
    status.textContent = "Загрузка распознавания…";
    try {
      status.textContent = "Ожидание доступа к камере…";
      const camera = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: "user" },
      });
      if (signal.aborted) {
        camera.getTracks().forEach((track) => track.stop());
        return;
      }
      stream = camera;
      video.srcObject = camera;
      video.hidden = false;
      await video.play();
      if (signal.aborted) return;

      const [{ HolisticDetector }, recognition] = await Promise.all([
        import("./holistic"), import("./sign-recognition"),
      ]);
      const library = references ?? await recognition.loadSignReferences(signal);
      if (signal.aborted) return;
      references = library;
      const model = detector ?? await HolisticDetector.create({
        wasmBasePath: panel.dataset.mediapipeWasm ?? "",
        modelUrl: panel.dataset.mediapipeModelUrl ?? "",
      });
      if (signal.aborted) {
        model.dispose();
        return;
      }
      detector = model;
      const frames: NonNullable<ReturnType<typeof signFeatures>>[] = [];
      let startedAt = 0;
      let lastHandAt = 0;
      let waitForPause = false;
      complete = () => {
        if (!frames.length) return;
        const result = recognition.recognizeSign(frames.splice(0), library);
        startedAt = 0;
        waitForPause = true;
        if (!result) {
          status.textContent = "Жест не удалось уверенно распознать. Попробуйте ещё раз или введите текст.";
          return;
        }
        const text = [draft.value.trim(), result].filter(Boolean).join(" ");
        if (text.length > draft.maxLength) {
          status.textContent = "Черновик заполнен. Перенесите его в чат и продолжите.";
          return;
        }
        draft.value = text;
        syncDraft();
        status.textContent = `Распознано: «${result}». Проверьте текст перед отправкой.`;
      };


      let lastVideoTime = -1;
      finish.hidden = false;
      status.textContent = "Покажите жест и уберите руки из кадра для следующего слова.";
      timer = window.setInterval(() => {
        const now = performance.now();

        if (video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA || video.currentTime === lastVideoTime) return;
        lastVideoTime = video.currentTime;
        try {
          const frame = recognition.signFeatures(model.detectWorld(video, now));
          if (frame?.hands.some(Boolean)) {
            if (waitForPause) return;
            if (!startedAt) startedAt = now;
            lastHandAt = now;
            frames.push(frame);
            if (now - startedAt >= RECORDING_LIMIT_MS) complete?.();
          } else if (now - lastHandAt >= 350) {
            complete?.();
            waitForPause = false;
          }
        } catch {
          stopCapture();
          detector?.dispose();
          detector = null;
          status.textContent = "Не удалось обработать видео с камеры.";
        }
      }, SAMPLE_INTERVAL_MS);
    } catch (error) {
      if (signal.aborted) return;
      stopCapture();
      console.warn("Не удалось запустить распознавание жестов", error);
      status.textContent = error instanceof DOMException && error.name === "NotAllowedError"
        ? "Разрешите доступ к камере, чтобы распознавать жесты."
        : "Не удалось запустить распознавание. Проверьте камеру и подключение.";
    }
  });

  const pauseWhenHidden = (): void => {
    if (!document.hidden || !session) return;
    stopCapture();
    status.textContent = "Камера выключена после ухода со вкладки.";
  };
  document.addEventListener("visibilitychange", pauseWhenHidden);
  modes.hidden = false;
  return () => {
    setMode(false);
    modes.hidden = true;
    document.removeEventListener("visibilitychange", pauseWhenHidden);
  };
}
