/**
 * Тесты настроек студента (C7).
 *
 * Проверяются ограничения FR-13 (скорость 0.6–1.2x, размер и положение),
 * устойчивость к битым данным, сохранение между заходами и CSS-переменные,
 * которые применяет страница аватара.
 */

import { describe, expect, it } from "vitest";

import {
  STUDENT_OFFSET_MAX,
  STUDENT_OFFSET_MIN,
  STUDENT_SETTINGS_DEFAULTS,
  STUDENT_SETTINGS_KEY,
  STUDENT_SIZE_MAX,
  STUDENT_SIZE_MIN,
  STUDENT_SPEED_MAX,
  STUDENT_SPEED_MIN,
  STUDENT_THEME_BACKGROUNDS,
  loadStudentSettings,
  normalizeStudentSettings,
  parseStudentSettings,
  saveStudentSettings,
  serializeStudentSettings,
  studentSettingsCss,
  studentThemeBackground,
  type StudentSettingsStorage,
} from "./student-settings";

/** Хранилище в памяти вместо `localStorage` (тесты идут в Node). */
class MemoryStorage implements StudentSettingsStorage {
  private readonly values = new Map<string, string>();

  getItem(key: string): string | null {
    return this.values.get(key) ?? null;
  }

  setItem(key: string, value: string): void {
    this.values.set(key, value);
  }
}

describe("normalizeStudentSettings", () => {
  it("возвращает полные умолчания для пустого объекта", () => {
    expect(normalizeStudentSettings({})).toEqual(STUDENT_SETTINGS_DEFAULTS);
    expect(normalizeStudentSettings(null)).toEqual(STUDENT_SETTINGS_DEFAULTS);
  });

  it("сохраняет корректные поля и добирает недостающие из умолчаний", () => {
    expect(normalizeStudentSettings({ speed: 0.8, size: 1.25, theme: "light" })).toEqual({
      ...STUDENT_SETTINGS_DEFAULTS,
      speed: 0.8,
      size: 1.25,
      theme: "light",
    });
  });

  it("зажимает скорость студента в 0.6–1.2x (FR-13, не 1.3x)", () => {
    expect(normalizeStudentSettings({ speed: 2 }).speed).toBe(STUDENT_SPEED_MAX);
    expect(normalizeStudentSettings({ speed: 1.3 }).speed).toBe(1.2);
    expect(normalizeStudentSettings({ speed: 0.2 }).speed).toBe(STUDENT_SPEED_MIN);
  });

  it("зажимает размер и положение аватара", () => {
    const tooBig = normalizeStudentSettings({ size: 5, offsetX: 100, offsetY: -100 });
    expect(tooBig.size).toBe(STUDENT_SIZE_MAX);
    expect(tooBig.offsetX).toBe(STUDENT_OFFSET_MAX);
    expect(tooBig.offsetY).toBe(STUDENT_OFFSET_MIN);

    const tooSmall = normalizeStudentSettings({ size: 0.1 });
    expect(tooSmall.size).toBe(STUDENT_SIZE_MIN);
  });

  it("игнорирует мусор и неизвестную тему", () => {
    const settings = normalizeStudentSettings({
      speed: "быстро",
      size: Number.NaN,
      offsetX: null,
      theme: "neon",
    });
    expect(settings).toEqual(STUDENT_SETTINGS_DEFAULTS);
  });

  it("принимает числа строками (старые записи хранилища)", () => {
    const settings = normalizeStudentSettings({ speed: "0.75", size: "1.2", offsetX: "-10" });
    expect(settings.speed).toBe(0.75);
    expect(settings.size).toBe(1.2);
    expect(settings.offsetX).toBe(-10);
  });

  it("не мутирует объект умолчаний", () => {
    normalizeStudentSettings({ speed: 0.6, theme: "light" });
    expect(STUDENT_SETTINGS_DEFAULTS).toEqual({
      speed: 1,
      size: 1,
      offsetX: 0,
      offsetY: 0,
      theme: "dark",
    });
  });
});

describe("parse / serialize", () => {
  it("переживает битый JSON и пустую строку", () => {
    expect(parseStudentSettings("{не json")).toEqual(STUDENT_SETTINGS_DEFAULTS);
    expect(parseStudentSettings("")).toEqual(STUDENT_SETTINGS_DEFAULTS);
    expect(parseStudentSettings(null)).toEqual(STUDENT_SETTINGS_DEFAULTS);
  });

  it("делает круговой обход через строку с нормализацией", () => {
    const raw = serializeStudentSettings({
      speed: 1.4,
      size: 0.8,
      offsetX: 5,
      offsetY: -5,
      theme: "light",
    });
    expect(parseStudentSettings(raw)).toEqual({
      speed: 1.2,
      size: 0.8,
      offsetX: 5,
      offsetY: -5,
      theme: "light",
    });
  });
});

describe("loadStudentSettings / saveStudentSettings", () => {
  it("сохраняет настройки между заходами", () => {
    const storage = new MemoryStorage();
    const saved = saveStudentSettings(
      { speed: 0.7, size: 1.4, offsetX: 10, offsetY: -15, theme: "light" },
      storage,
    );

    expect(loadStudentSettings(storage)).toEqual(saved);
    // «Новый заход» читает то же хранилище, а не память прошлого экземпляра.
    expect(loadStudentSettings(storage).theme).toBe("light");
    expect(storage.getItem(STUDENT_SETTINGS_KEY)).toContain('"speed":0.7');
  });

  it("возвращает нормализованные настройки из save", () => {
    const storage = new MemoryStorage();
    expect(saveStudentSettings({ ...STUDENT_SETTINGS_DEFAULTS, speed: 9 }, storage).speed).toBe(1.2);
    expect(loadStudentSettings(storage).speed).toBe(1.2);
  });

  it("не падает без хранилища", () => {
    expect(loadStudentSettings(null)).toEqual(STUDENT_SETTINGS_DEFAULTS);
    expect(saveStudentSettings(STUDENT_SETTINGS_DEFAULTS, null)).toEqual(STUDENT_SETTINGS_DEFAULTS);
    expect(loadStudentSettings(undefined)).toEqual(STUDENT_SETTINGS_DEFAULTS);
  });

  it("не падает на битой записи в хранилище", () => {
    const storage = new MemoryStorage();
    storage.setItem(STUDENT_SETTINGS_KEY, "сломано");
    expect(loadStudentSettings(storage)).toEqual(STUDENT_SETTINGS_DEFAULTS);
  });
});

describe("studentSettingsCss", () => {
  it("отдаёт масштаб, сдвиг и цвет фона для сцены", () => {
    expect(
      studentSettingsCss({
        speed: 0.9,
        size: 1.25,
        offsetX: 10,
        offsetY: -5,
        theme: "light",
      }),
    ).toEqual({
      "--avatar-size": "1.25",
      "--avatar-offset-x": "10%",
      "--avatar-offset-y": "-5%",
      "--avatar-bg": STUDENT_THEME_BACKGROUNDS.light,
    });
  });

  it("нормализует значения перед выводом в CSS", () => {
    expect(studentSettingsCss({ ...STUDENT_SETTINGS_DEFAULTS, size: 10 })["--avatar-size"]).toBe("1.6");
  });

  it("даёт контрастный фон для обеих тем", () => {
    expect(studentThemeBackground("dark")).toBe("#111827");
    expect(studentThemeBackground("light")).toBe("#f8fafc");
    expect(studentThemeBackground("dark")).not.toBe(studentThemeBackground("light"));
  });
});
