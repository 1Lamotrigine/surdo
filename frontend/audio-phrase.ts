/**
 * Аудиофраза преподавателя (F7): WAV 16 кГц mono и отправка в F6 API.
 *
 * VAD (`vad-web`) отдаёт готовый фрагмент речи как `Float32Array` с частотой
 * 16 кГц. Сервер принимает WAV/Opus, поэтому здесь Float32 превращается в
 * обычный PCM WAV без внешних библиотек: 16-битные сэмплы, little-endian,
 * один канал. Модуль не зависит от DOM — его можно тестировать в Node.
 */

/** Формат, который ждёт `services.asr` и F6 endpoint. */
export const PHRASE_SAMPLE_RATE = 16_000;
export const PHRASE_CHANNELS = 1;
export const PHRASE_BITS_PER_SAMPLE = 16;
export const WAV_HEADER_BYTES = 44;

const PCM_FORMAT = 1;

export class PhraseUploadError extends Error {
  readonly status: number;

  constructor(message: string, status = 0) {
    super(message);
    this.name = "PhraseUploadError";
    this.status = status;
  }
}

function ascii(view: DataView, offset: number, value: string): void {
  for (let index = 0; index < value.length; index += 1) {
    view.setUint8(offset + index, value.charCodeAt(index));
  }
}

/**
 * Превратить Float32 в PCM16 WAV. Значения вне [-1, 1] обрезаются, NaN и
 * бесконечности заменяются тишиной: такой файл не сломает разбор на сервере.
 */
export function encodeWav(
  samples: Float32Array,
  sampleRate: number = PHRASE_SAMPLE_RATE,
): Uint8Array {
  if (!Number.isInteger(sampleRate) || sampleRate <= 0) {
    throw new RangeError("Частота дискретизации должна быть положительным целым числом.");
  }

  const dataBytes = samples.length * (PHRASE_BITS_PER_SAMPLE / 8);
  const buffer = new ArrayBuffer(WAV_HEADER_BYTES + dataBytes);
  const view = new DataView(buffer);

  ascii(view, 0, "RIFF");
  view.setUint32(4, 36 + dataBytes, true);
  ascii(view, 8, "WAVE");
  ascii(view, 12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, PCM_FORMAT, true);
  view.setUint16(22, PHRASE_CHANNELS, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(
    28,
    sampleRate * PHRASE_CHANNELS * (PHRASE_BITS_PER_SAMPLE / 8),
    true,
  );
  view.setUint16(32, PHRASE_CHANNELS * (PHRASE_BITS_PER_SAMPLE / 8), true);
  view.setUint16(34, PHRASE_BITS_PER_SAMPLE, true);
  ascii(view, 36, "data");
  view.setUint32(40, dataBytes, true);

  for (let index = 0; index < samples.length; index += 1) {
    const sample = Number.isFinite(samples[index]) ? samples[index] : 0;
    const clamped = Math.max(-1, Math.min(1, sample));
    const value = clamped < 0 ? Math.round(clamped * 0x8000) : Math.round(clamped * 0x7fff);
    view.setInt16(WAV_HEADER_BYTES + index * 2, value, true);
  }

  return new Uint8Array(buffer);
}

export type UploadPhraseOptions = {
  /** URL вида `/api/rooms/<code>/phrase/`. */
  url: string;
  /** CSRF-токен комнаты: сервер проверяет его у multipart POST. */
  csrfToken: string;
  /** Готовый WAV 16 кГц mono. */
  audio: Uint8Array;
  filename?: string;
  /** Подмена fetch для тестов; в браузере используется глобальный. */
  fetchImpl?: typeof fetch;
};

async function errorDetail(response: Response): Promise<string> {
  try {
    const payload: unknown = await response.json();
    if (
      payload &&
      typeof payload === "object" &&
      typeof (payload as { detail?: unknown }).detail === "string"
    ) {
      return (payload as { detail: string }).detail;
    }
  } catch {
    // Ниже общий текст: тело ответа не JSON.
  }
  return `Сервер ответил ${response.status}.`;
}

/**
 * Отправить одну фразу multipart-запросом в F6 endpoint. Аудио остаётся в
 * памяти браузера и не попадает в localStorage или на диск.
 */
export async function uploadPhrase(options: UploadPhraseOptions): Promise<void> {
  const fetchImpl = options.fetchImpl ?? globalThis.fetch;
  if (!fetchImpl) {
    throw new PhraseUploadError("Браузер не поддерживает fetch.");
  }

  const form = new FormData();
  form.append(
    "audio",
    new Blob([options.audio as BlobPart], { type: "audio/wav" }),
    options.filename ?? "phrase.wav",
  );

  let response: Response;
  try {
    response = await fetchImpl(options.url, {
      method: "POST",
      headers: {
        Accept: "application/json",
        "X-CSRFToken": options.csrfToken,
      },
      body: form,
      credentials: "same-origin",
    });
  } catch {
    throw new PhraseUploadError("Не удалось отправить фразу: нет соединения.");
  }

  if (!response.ok) {
    throw new PhraseUploadError(await errorDetail(response), response.status);
  }
}
