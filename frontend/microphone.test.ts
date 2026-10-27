import { describe, expect, it } from "vitest";

import { PhraseUploadError, type UploadPhraseOptions } from "./audio-phrase";
import {
  MicrophoneController,
  microphoneErrorMessage,
  type MicrophoneElements,
  type SpeechData,
  type VadHandlers,
  type VadRecorder,
} from "./microphone";

function fakePanel(): HTMLElement {
  return { dataset: {} } as unknown as HTMLElement;
}

function fakeButton(disabled = false) {
  const attributes = new Map<string, string>();
  const element = {
    disabled,
    textContent: "",
    setAttribute: (name: string, value: string) => attributes.set(name, value),
  } as unknown as HTMLButtonElement;
  return { element, attributes };
}

function fakeText() {
  return { dataset: {}, textContent: "", hidden: false } as unknown as HTMLElement;
}

function fakeUi(disabled = false): {
  elements: MicrophoneElements;
  button: ReturnType<typeof fakeButton>;
  status: HTMLElement;
  count: HTMLElement;
} {
  const button = fakeButton(disabled);
  const status = fakeText();
  const count = fakeText();
  return {
    elements: {
      panel: fakePanel(),
      toggle: button.element,
      status,
      count,
    },
    button,
    status,
    count,
  };
}

function fakeVad() {
  let handlers: VadHandlers | undefined;
  let disposeCalls = 0;
  const recorder: VadRecorder = async (nextHandlers) => {
    handlers = nextHandlers;
    return async () => {
      disposeCalls += 1;
    };
  };
  return {
    recorder,
    get handlers(): VadHandlers | undefined {
      return handlers;
    },
    get disposeCalls(): number {
      return disposeCalls;
    },
  };
}

function speech(samples = [0.5, -0.5]): SpeechData {
  return {
    audioData: new Float32Array(samples),
    sampleRate: 16_000,
    startTime: 1000,
    endTime: 1500,
  };
}

async function flush(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, 0));
}

describe("microphoneErrorMessage", () => {
  it("переводит отказ доступа и отсутствие HTTPS на понятный текст", () => {
    expect(
      microphoneErrorMessage({
        name: "NotAllowedError",
        message: "Permission denied",
      }),
    ).toContain("Доступ к микрофону запрещён");

    expect(
      microphoneErrorMessage(
        new Error("Missing AudioWorklet support. Maybe this is not running in a secure context."),
      ),
    ).toContain("только по HTTPS");
  });
});

describe("MicrophoneController", () => {
  it("включает VAD, показывает речь и отправляет готовую фразу", async () => {
    const ui = fakeUi();
    const vad = fakeVad();
    const uploads: UploadPhraseOptions[] = [];
    const controller = new MicrophoneController(ui.elements, {
      phraseUrl: "/api/rooms/ABCDEF/phrase/",
      csrfToken: "token",
      loadRecorder: async () => vad.recorder,
      upload: async (options) => {
        uploads.push(options);
      },
    });

    await controller.start();

    expect(controller.isActive).toBe(true);
    expect(ui.button.element.textContent).toBe("Остановить микрофон");
    expect(ui.button.attributes.get("aria-pressed")).toBe("true");
    expect(ui.status.textContent).toContain("Слушаю");

    vad.handlers?.onSpeechStart?.();
    expect(ui.status.textContent).toBe("Слышу речь…");

    vad.handlers?.onSpeechAvailable?.(speech());
    expect(ui.status.dataset.state).toBe("uploading");
    await flush();

    expect(uploads).toHaveLength(1);
    expect(uploads[0].url).toBe("/api/rooms/ABCDEF/phrase/");
    expect(uploads[0].csrfToken).toBe("token");
    expect(new TextDecoder().decode(uploads[0].audio.slice(0, 4))).toBe("RIFF");
    expect(ui.status.dataset.state).toBe("listening");
    expect(ui.count.textContent).toContain("Отправлено фраз: 1");

    await controller.stop();

    expect(vad.disposeCalls).toBe(1);
    expect(controller.isActive).toBe(false);
    expect(ui.status.textContent).toContain("Отправлено фраз: 1");
  });

  it("отправляет фразы строго по одной и в порядке речи", async () => {
    const ui = fakeUi();
    const vad = fakeVad();
    const uploads: UploadPhraseOptions[] = [];
    const releases: Array<() => void> = [];
    const controller = new MicrophoneController(ui.elements, {
      phraseUrl: "/phrase/",
      csrfToken: "token",
      loadRecorder: async () => vad.recorder,
      upload: (options) =>
        new Promise<void>((resolve) => {
          uploads.push(options);
          releases.push(resolve);
        }),
    });
    await controller.start();

    vad.handlers?.onSpeechAvailable?.(speech([1]));
    vad.handlers?.onSpeechAvailable?.(speech([-1]));
    await flush();
    expect(uploads).toHaveLength(1);
    expect(controller.pending).toBe(2);

    releases[0]();
    await flush();
    expect(uploads).toHaveLength(2);

    releases[1]();
    await flush();
    expect(controller.pending).toBe(0);
    expect(ui.count.textContent).toContain("Отправлено фраз: 2");

    await controller.stop();
  });

  it("оставляет микрофон включённым при ошибке отправки", async () => {
    const ui = fakeUi();
    const vad = fakeVad();
    const controller = new MicrophoneController(ui.elements, {
      phraseUrl: "/phrase/",
      csrfToken: "token",
      loadRecorder: async () => vad.recorder,
      upload: async () => {
        throw new PhraseUploadError("Комната закрыта.", 404);
      },
    });
    await controller.start();

    vad.handlers?.onSpeechAvailable?.(speech());
    await flush();

    expect(controller.isActive).toBe(true);
    expect(ui.button.element.disabled).toBe(false);
    expect(ui.status.dataset.state).toBe("error");
    expect(ui.status.textContent).toContain("Не удалось отправить фразу: Комната закрыта.");

    await controller.stop();
  });

  it("не запускает VAD в закрытой комнате", async () => {
    const ui = fakeUi(true);
    let loads = 0;
    const controller = new MicrophoneController(ui.elements, {
      phraseUrl: "/phrase/",
      csrfToken: "token",
      loadRecorder: async () => {
        loads += 1;
        return fakeVad().recorder;
      },
    });

    await controller.start();

    expect(loads).toBe(0);
    expect(controller.isActive).toBe(false);
    expect(ui.button.element.disabled).toBe(true);
    expect(ui.status.textContent).toBe("Комната закрыта: микрофон недоступен.");
  });

  it("показывает ошибку старта и не блокирует текстовую форму", async () => {
    const ui = fakeUi();
    const controller = new MicrophoneController(ui.elements, {
      phraseUrl: "/phrase/",
      csrfToken: "token",
      loadRecorder: async () => {
        throw new Error("Missing AudioWorklet support in secure context");
      },
    });

    await controller.start();

    expect(controller.isActive).toBe(false);
    expect(ui.button.element.disabled).toBe(false);
    expect(ui.button.element.textContent).toBe("Включить микрофон");
    expect(ui.status.dataset.state).toBe("error");
    expect(ui.status.textContent).toContain("только по HTTPS");
  });

  it("выключает микрофон и запрещает повторный запуск после disable", async () => {
    const ui = fakeUi();
    const vad = fakeVad();
    const controller = new MicrophoneController(ui.elements, {
      phraseUrl: "/phrase/",
      csrfToken: "token",
      loadRecorder: async () => vad.recorder,
    });
    await controller.start();

    controller.disable();
    await flush();

    expect(controller.isActive).toBe(false);
    expect(ui.button.element.disabled).toBe(true);
    expect(ui.status.textContent).toBe("Комната закрыта: микрофон недоступен.");

    await controller.start();
    expect(controller.isActive).toBe(false);
  });
});
