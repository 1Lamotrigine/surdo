/**
 * Черновик жеста (D3): проверка метаданных и отправка клипа в `POST /api/signs/`.
 *
 * Модуль не читает DOM и не зависит от страницы: форма передаёт сюда значения
 * полей и готовый `.json.gz`, а обратно приходит созданный жест. Ошибки сервера
 * сохраняются в `SignDraftError`, чтобы интерфейс показал текст из API, а не
 * общий «что-то пошло не так».
 */

export const GLOSS_MAX_LENGTH = 100;

/** Языки, которые сейчас принимает сервер (`dictionary.models.Language`). */
export const SIGN_LANGUAGES = ["rsl", "ksl"] as const;
export type SignLanguage = (typeof SIGN_LANGUAGES)[number];

export type SignDraft = {
  gloss: string;
  lang: string;
  description: string;
};

export type SignDraftErrors = Partial<Record<"gloss" | "lang", string>>;

export type SignDraftValidation = {
  draft: SignDraft;
  errors: SignDraftErrors;
  valid: boolean;
};

export type SignApiUnknownWord = {
  id: number;
  lemma: string;
  status: string;
  [key: string]: unknown;
};

export type SignApiSign = {
  id: number;
  gloss: string;
  lang: string;
  status: string;
  unknown_word?: SignApiUnknownWord;
  [key: string]: unknown;
};

export type SubmitSignDraftOptions = {
  url: string;
  csrfToken: string;
  draft: SignDraft;
  /** Содержимое `.json.gz` в виде Blob (обычно создаётся из Uint8Array). */
  file: Blob;
  /** Слово очереди (D4): после создания жеста станет `recorded`. */
  unknownWordId?: number | null;
  filename?: string;
  /** Подмена fetch для тестов; в браузере используется глобальный. */
  fetchImpl?: typeof fetch;
};

export class SignDraftError extends Error {
  readonly status: number;

  constructor(message: string, status = 0) {
    super(message);
    this.name = "SignDraftError";
    this.status = status;
  }
}

/**
 * Нормализовать метаданные так же, как сервер: глосса без лишних пробелов,
 * описание без пробелов по краям. Пустая глосса и неизвестный язык — ошибки.
 */
export function validateSignDraft(
  input: Partial<SignDraft>,
  allowedLanguages: readonly string[] = SIGN_LANGUAGES,
): SignDraftValidation {
  const gloss = (input.gloss ?? "").trim().replace(/\s+/g, " ");
  const lang = (input.lang ?? "").trim() || "rsl";
  const description = (input.description ?? "").trim();
  const errors: SignDraftErrors = {};

  if (!gloss) {
    errors.gloss = "Укажите глоссу жеста.";
  } else if (gloss.length > GLOSS_MAX_LENGTH) {
    errors.gloss = `Глосса длиннее ${GLOSS_MAX_LENGTH} символов.`;
  }
  if (!allowedLanguages.includes(lang)) {
    errors.lang = `Неизвестный язык: ${lang}.`;
  }

  return {
    draft: { gloss, lang, description },
    errors,
    valid: Object.keys(errors).length === 0,
  };
}

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
    // Ниже вернём общий текст: тело ответа не JSON.
  }
  return `Сервер ответил ${response.status}.`;
}

/**
 * Отправить метаданные и клип как `multipart/form-data`. Жест всегда создаётся
 * черновиком — статус меняет эксперт позже (FR-19).
 */
export async function submitSignDraft(
  options: SubmitSignDraftOptions,
): Promise<SignApiSign> {
  const form = new FormData();
  form.append("gloss", options.draft.gloss);
  form.append("lang", options.draft.lang);
  form.append("description", options.draft.description);
  if (options.unknownWordId !== undefined && options.unknownWordId !== null) {
    form.append("unknown_word", String(options.unknownWordId));
  }
  form.append(
    "clip",
    options.file,
    options.filename ?? "gesture.json.gz",
  );

  const fetchImpl = options.fetchImpl ?? globalThis.fetch;
  if (!fetchImpl) {
    throw new SignDraftError("Браузер не поддерживает fetch.");
  }

  const response = await fetchImpl(options.url, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "X-CSRFToken": options.csrfToken,
    },
    body: form,
    credentials: "same-origin",
  });

  if (!response.ok) {
    throw new SignDraftError(await errorDetail(response), response.status);
  }

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new SignDraftError("Сервер вернул не JSON.", response.status);
  }
  if (
    !payload ||
    typeof payload !== "object" ||
    typeof (payload as { id?: unknown }).id !== "number"
  ) {
    throw new SignDraftError("В ответе API нет номера созданного жеста.", response.status);
  }
  return payload as SignApiSign;
}
