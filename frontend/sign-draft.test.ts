import { describe, expect, it } from "vitest";

import {
  GLOSS_MAX_LENGTH,
  SignDraftError,
  submitSignDraft,
  validateSignDraft,
} from "./sign-draft";

describe("validateSignDraft", () => {
  it("нормализует глоссу и описание", () => {
    const result = validateSignDraft({
      gloss: "  УЧЕБНИК   школа ",
      lang: "rsl",
      description: "  школьный жест  ",
    });

    expect(result.valid).toBe(true);
    expect(result.draft).toEqual({
      gloss: "УЧЕБНИК школа",
      lang: "rsl",
      description: "школьный жест",
    });
    expect(result.errors).toEqual({});
  });

  it("подставляет русский жестовый язык по умолчанию", () => {
    const result = validateSignDraft({ gloss: "ЖЕСТ" });

    expect(result.valid).toBe(true);
    expect(result.draft.lang).toBe("rsl");
  });

  it("требует непустую глоссу", () => {
    const result = validateSignDraft({ gloss: "   ", lang: "rsl" });

    expect(result.valid).toBe(false);
    expect(result.errors.gloss).toContain("Укажите глоссу");
  });

  it("ограничивает длину глоссы", () => {
    const result = validateSignDraft({ gloss: "Ж".repeat(GLOSS_MAX_LENGTH + 1) });

    expect(result.valid).toBe(false);
    expect(result.errors.gloss).toContain(String(GLOSS_MAX_LENGTH));
  });

  it("отклоняет неизвестный язык", () => {
    const result = validateSignDraft({ gloss: "ЖЕСТ", lang: "xx" }, ["rsl", "ksl"]);

    expect(result.valid).toBe(false);
    expect(result.errors.lang).toContain("xx");
  });
});

describe("submitSignDraft", () => {
  it("отправляет поля и клип в multipart-форме", async () => {
    let capturedUrl = "";
    let capturedInit: RequestInit | undefined;

    const fetchImpl = (async (url: string | URL | Request, init?: RequestInit) => {
      capturedUrl = String(url);
      capturedInit = init;
      return {
        ok: true,
        status: 201,
        json: async () => ({ id: 7, gloss: "УЧЕБНИК", lang: "rsl", status: "draft" }),
      } as Response;
    }) as typeof fetch;

    const file = new Blob([new Uint8Array([1, 2, 3])], { type: "application/gzip" });
    const result = await submitSignDraft({
      url: "/api/signs/",
      csrfToken: "token-123",
      draft: { gloss: "УЧЕБНИК", lang: "rsl", description: "школьный" },
      file,
      filename: "clip.json.gz",
      fetchImpl,
    });

    expect(result.id).toBe(7);
    expect(capturedUrl).toBe("/api/signs/");
    expect(capturedInit?.method).toBe("POST");
    expect((capturedInit?.headers as Record<string, string>)["X-CSRFToken"]).toBe("token-123");
    const form = capturedInit?.body as FormData;
    expect(form.get("gloss")).toBe("УЧЕБНИК");
    expect(form.get("lang")).toBe("rsl");
    expect(form.get("description")).toBe("школьный");
    const uploaded = form.get("clip");
    expect(uploaded).toBeInstanceOf(Blob);
    expect((uploaded as File).name).toBe("clip.json.gz");
  });

  it("передаёт текст ошибки API", async () => {
    const fetchImpl = (async () =>
      ({
        ok: false,
        status: 400,
        json: async () => ({ detail: "Укажите глоссу жеста." }),
      }) as Response) as typeof fetch;

    await expect(
      submitSignDraft({
        url: "/api/signs/",
        csrfToken: "token",
        draft: { gloss: "", lang: "rsl", description: "" },
        file: new Blob([]),
        fetchImpl,
      }),
    ).rejects.toMatchObject({
      name: "SignDraftError",
      status: 400,
      message: "Укажите глоссу жеста.",
    });
  });

  it("отклоняет ответ без номера жеста", async () => {
    const fetchImpl = (async () =>
      ({
        ok: true,
        status: 201,
        json: async () => ({ gloss: "ЖЕСТ" }),
      }) as Response) as typeof fetch;

    await expect(
      submitSignDraft({
        url: "/api/signs/",
        csrfToken: "token",
        draft: { gloss: "ЖЕСТ", lang: "rsl", description: "" },
        file: new Blob([]),
        fetchImpl,
      }),
    ).rejects.toThrow(SignDraftError);
  });
});
