/**
 * Тесты загрузчика анимационных клипов (H1).
 *
 * Полный разбор GLB требует настоящего файла с BIN-дорожками, поэтому здесь
 * проверяются чистые части: чтение JSON-чанка, распознавание VRMA, число
 * анимаций и понятные ошибки на битых/неподдерживаемых файлах.
 */

import { describe, expect, it } from "vitest";

import {
  AnimationFormatError,
  VrmaNotSupportedError,
  animationCount,
  glbJson,
  isVrmaJson,
  loadAnimationBundle,
  pickAnimationClip,
  type AnimationBundle,
} from "./animation-clip";

const GLB_MAGIC = 0x46546c67;
const JSON_CHUNK = 0x4e4f534a;

function glb(payload: unknown): ArrayBuffer {
  const raw = new TextEncoder().encode(JSON.stringify(payload));
  const padded = new Uint8Array(Math.ceil(raw.length / 4) * 4);
  padded.set(raw);
  padded.fill(0x20, raw.length); // пробелы, как требует GLB
  const buffer = new ArrayBuffer(12 + 8 + padded.length);
  const view = new DataView(buffer);
  view.setUint32(0, GLB_MAGIC, true);
  view.setUint32(4, 2, true);
  view.setUint32(8, buffer.byteLength, true);
  view.setUint32(12, padded.length, true);
  view.setUint32(16, JSON_CHUNK, true);
  new Uint8Array(buffer).set(padded, 20);
  return buffer;
}

function payload(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    asset: { version: "2.0" },
    animations: [{ name: "gesture" }],
    ...overrides,
  };
}

describe("glbJson", () => {
  it("читает JSON-чанк GLB", () => {
    const parsed = glbJson(glb(payload()));
    expect(parsed?.asset).toEqual({ version: "2.0" });
  });

  it("возвращает null для не-GLB", () => {
    const buffer = new TextEncoder().encode("not a glb").buffer;
    expect(glbJson(buffer)).toBeNull();
  });

  it("возвращает null при несовпадении длины", () => {
    const buffer = glb(payload());
    new DataView(buffer).setUint32(8, 999, true);
    expect(glbJson(buffer)).toBeNull();
  });
});

describe("isVrmaJson", () => {
  it("распознаёт расширение VRMC_vrm_animation", () => {
    expect(isVrmaJson(payload({ extensionsUsed: ["VRMC_vrm_animation"] }))).toBe(true);
  });

  it("обычный glTF — не VRMA", () => {
    expect(isVrmaJson(payload())).toBe(false);
    expect(isVrmaJson(payload({ extensionsUsed: ["KHR_materials_unlit"] }))).toBe(false);
  });
});

describe("animationCount", () => {
  it("считает анимации", () => {
    expect(animationCount(payload())).toBe(1);
    expect(animationCount(payload({ animations: [{}, {}, {}] }))).toBe(3);
    expect(animationCount(payload({ animations: undefined }))).toBe(0);
  });
});

describe("pickAnimationClip", () => {
  const bundle = {
    clips: [{ name: "uchebnik" }, { name: "daktil_a" }],
    vrma: false,
    url: "https://example.test/g.glb",
  } as unknown as AnimationBundle;

  it("без имени берёт первую анимацию файла", () => {
    expect(pickAnimationClip(bundle)?.name).toBe("uchebnik");
    expect(pickAnimationClip(bundle, "  ")?.name).toBe("uchebnik");
  });

  it("выбирает запись по имени", () => {
    expect(pickAnimationClip(bundle, "daktil_a")?.name).toBe("daktil_a");
  });

  it("не подменяет отсутствующую запись первой", () => {
    expect(pickAnimationClip(bundle, "net-takoy")).toBeNull();
    expect(pickAnimationClip({ ...bundle, clips: [] }, "uchebnik")).toBeNull();
  });
});

describe("loadAnimationBundle", () => {
  it("на VRMA сообщает о неподключённом пакете", async () => {
    const buffer = glb(payload({ extensionsUsed: ["VRMC_vrm_animation"] }));
    await expect(
      loadAnimationBundle("https://example.test/a.vrma", { fetcher: async () => buffer }),
    ).rejects.toBeInstanceOf(VrmaNotSupportedError);
  });

  it("на файле без анимаций бросает ошибку формата", async () => {
    const buffer = glb(payload({ animations: [] }));
    await expect(
      loadAnimationBundle("https://example.test/a.glb", { fetcher: async () => buffer }),
    ).rejects.toBeInstanceOf(AnimationFormatError);
  });

  it("на битом контейнере бросает ошибку формата", async () => {
    const buffer = new TextEncoder().encode("nope").buffer;
    await expect(
      loadAnimationBundle("https://example.test/a.glb", { fetcher: async () => buffer }),
    ).rejects.toBeInstanceOf(AnimationFormatError);
  });
});
