/**
 * Настройки студента (C7): скорость, размер, положение аватара и тёмный/светлый
 * фон (FR-13). Настройки сохраняются между заходами в браузере (`localStorage`),
 * поэтому студенту не нужно выставлять их заново каждый раз.
 *
 * Здесь живёт **чистая** часть: ограничения, нормализация, чтение/запись в
 * хранилище и CSS-переменные для сцены. DOM-слой `StudentSettingsView` только
 * связывает поля формы с этими функциями — сцена и плеер остаются снаружи.
 *
 * Скорость студента ограничена 0.6–1.2x (FR-13), хотя планировщик C4 допускает
 * до 1.3x: верхняя планка нужна для догона отставания (FR-16), а не для
 * ручной настройки.
 */

import { DEFAULT_AVATAR_SPEED } from "./clip-queue";

/** Тема фона сцены (FR-13). */
export type StudentTheme = "dark" | "light";

/** Настройки студента. */
export type StudentSettings = {
  /** Скорость воспроизведения, 0.6–1.2x. */
  speed: number;
  /** Масштаб аватара в кадре, 0.6–1.6. */
  size: number;
  /** Горизонтальный сдвиг аватара, % ширины сцены. */
  offsetX: number;
  /** Вертикальный сдвиг аватара, % высоты сцены. */
  offsetY: number;
  /** Тёмный или светлый фон. */
  theme: StudentTheme;
};

/** Настройки по умолчанию: нейтральный кадр и тёмный фон. */
export const STUDENT_SETTINGS_DEFAULTS: StudentSettings = {
  speed: DEFAULT_AVATAR_SPEED,
  size: 1,
  offsetX: 0,
  offsetY: 0,
  theme: "dark",
};

/** Минимальная скорость по FR-13. */
export const STUDENT_SPEED_MIN = 0.6;
/** Максимальная скорость, доступная студенту (FR-13: 0.6–1.2x). */
export const STUDENT_SPEED_MAX = 1.2;
/** Минимальный масштаб аватара. */
export const STUDENT_SIZE_MIN = 0.6;
/** Максимальный масштаб аватара. */
export const STUDENT_SIZE_MAX = 1.6;
/** Предел сдвига аватара (в процентах сцены). */
export const STUDENT_OFFSET_MIN = -40;
/** Предел сдвига аватара (в процентах сцены). */
export const STUDENT_OFFSET_MAX = 40;

/** Ключ настроек в `localStorage` (с версией — старый формат можно не читать). */
export const STUDENT_SETTINGS_KEY = "gluho-nemye:student-settings:v1";

/** Доступные темы фона. */
export const STUDENT_THEMES: StudentTheme[] = ["dark", "light"];

/** Цвет фона сцены для темы (контрастный в обе стороны). */
export const STUDENT_THEME_BACKGROUNDS: Record<StudentTheme, string> = {
  dark: "#111827",
  light: "#f8fafc",
};

/** Минимальное хранилище, нужное настройкам (удобно подменять в тестах). */
export type StudentSettingsStorage = Pick<Storage, "getItem" | "setItem">;

/** CSS-переменные, которые сцена читает из `style` контейнера. */
export type StudentSettingsCss = {
  "--avatar-size": string;
  "--avatar-offset-x": string;
  "--avatar-offset-y": string;
  "--avatar-bg": string;
};

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

/** Привести число к диапазону и двум знакам; мусор заменяется значением по умолчанию. */
function numberInRange(value: unknown, fallback: number, min: number, max: number): number {
  const raw =
    typeof value === "number" ? value : typeof value === "string" ? Number.parseFloat(value) : Number.NaN;
  if (!Number.isFinite(raw)) return fallback;
  return Math.round(clamp(raw, min, max) * 100) / 100;
}

function themeOrDefault(value: unknown): StudentTheme {
  return value === "light" || value === "dark" ? value : STUDENT_SETTINGS_DEFAULTS.theme;
}

/**
 * Привести произвольный объект к полным настройкам: недостающие поля берутся по
 * умолчанию, числа зажимаются в допустимые диапазоны. Функция терпима к старым
 * или частично испорченным данным из хранилища.
 */
export function normalizeStudentSettings(raw: unknown): StudentSettings {
  const input = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
  return {
    speed: numberInRange(
      input.speed,
      STUDENT_SETTINGS_DEFAULTS.speed,
      STUDENT_SPEED_MIN,
      STUDENT_SPEED_MAX,
    ),
    size: numberInRange(
      input.size,
      STUDENT_SETTINGS_DEFAULTS.size,
      STUDENT_SIZE_MIN,
      STUDENT_SIZE_MAX,
    ),
    offsetX: numberInRange(
      input.offsetX,
      STUDENT_SETTINGS_DEFAULTS.offsetX,
      STUDENT_OFFSET_MIN,
      STUDENT_OFFSET_MAX,
    ),
    offsetY: numberInRange(
      input.offsetY,
      STUDENT_SETTINGS_DEFAULTS.offsetY,
      STUDENT_OFFSET_MIN,
      STUDENT_OFFSET_MAX,
    ),
    theme: themeOrDefault(input.theme),
  };
}

/** Прочитать настройки из строки; битый JSON не ломает страницу — отдаём умолчания. */
export function parseStudentSettings(raw: string | null | undefined): StudentSettings {
  if (!raw) return { ...STUDENT_SETTINGS_DEFAULTS };
  try {
    return normalizeStudentSettings(JSON.parse(raw));
  } catch {
    return { ...STUDENT_SETTINGS_DEFAULTS };
  }
}

/** Сериализовать настройки для `localStorage` (в нормализованном виде). */
export function serializeStudentSettings(settings: StudentSettings): string {
  return JSON.stringify(normalizeStudentSettings(settings));
}

/** Найти `localStorage`, если он доступен (приватный режим может запретить доступ). */
function resolveStorage(
  storage: StudentSettingsStorage | null | undefined,
): StudentSettingsStorage | null {
  if (storage !== undefined) return storage;
  try {
    return globalThis.localStorage ?? null;
  } catch {
    return null;
  }
}

/**
 * Загрузить настройки из хранилища. Нет хранилища, нет записи или запись битая —
 * возвращаются умолчания, чтобы комната открывалась всегда.
 */
export function loadStudentSettings(
  storage?: StudentSettingsStorage | null,
): StudentSettings {
  const store = resolveStorage(storage);
  if (!store) return { ...STUDENT_SETTINGS_DEFAULTS };
  try {
    return parseStudentSettings(store.getItem(STUDENT_SETTINGS_KEY));
  } catch {
    return { ...STUDENT_SETTINGS_DEFAULTS };
  }
}

/**
 * Сохранить настройки в хранилище и вернуть нормализованное значение — его же
 * применяет страница, поэтому экран и хранилище не расходятся.
 */
export function saveStudentSettings(
  settings: StudentSettings,
  storage?: StudentSettingsStorage | null,
): StudentSettings {
  const normalized = normalizeStudentSettings(settings);
  const store = resolveStorage(storage);
  try {
    store?.setItem(STUDENT_SETTINGS_KEY, JSON.stringify(normalized));
  } catch {
    // Квота или запрет хранилища: настройки продолжают работать до перезагрузки.
  }
  return normalized;
}

/** CSS-переменные сцены: масштаб, сдвиг и цвет фона (значения живут в CSS). */
export function studentSettingsCss(settings: StudentSettings): StudentSettingsCss {
  const normalized = normalizeStudentSettings(settings);
  return {
    "--avatar-size": String(normalized.size),
    "--avatar-offset-x": `${normalized.offsetX}%`,
    "--avatar-offset-y": `${normalized.offsetY}%`,
    "--avatar-bg": STUDENT_THEME_BACKGROUNDS[normalized.theme],
  };
}

/** Цвет фона сцены для темы (нужен `Avatar.setBackground`). */
export function studentThemeBackground(theme: StudentTheme): string {
  return STUDENT_THEME_BACKGROUNDS[theme];
}

/** Параметры связывания формы настроек со страницей. */
export type StudentSettingsViewOptions = {
  /** Хранилище; `null` отключает сохранение (например, в тестах). */
  storage?: StudentSettingsStorage | null;
  /** Вызывается после загрузки и при каждом изменении настроек. */
  onChange?: (settings: StudentSettings) => void;
};

/**
 * Тонкий DOM-слой настроек: читает поля `[data-settings-*]`, сохраняет изменения
 * и отдаёт их странице через `onChange`. Ни сцены, ни плеера он не знает.
 */
export class StudentSettingsView {
  private readonly speed: HTMLInputElement | null;
  private readonly size: HTMLInputElement | null;
  private readonly offsetX: HTMLInputElement | null;
  private readonly offsetY: HTMLInputElement | null;
  private readonly theme: HTMLSelectElement | null;
  private readonly resetButton: HTMLButtonElement | null;
  private readonly speedOutput: HTMLOutputElement | null;
  private readonly sizeOutput: HTMLOutputElement | null;
  private readonly offsetXOutput: HTMLOutputElement | null;
  private readonly offsetYOutput: HTMLOutputElement | null;
  private readonly storage: StudentSettingsStorage | null | undefined;
  private readonly onChange?: StudentSettingsViewOptions["onChange"];
  private current: StudentSettings;

  constructor(root: HTMLElement, options: StudentSettingsViewOptions = {}) {
    this.storage = options.storage;
    this.onChange = options.onChange;
    this.current = loadStudentSettings(options.storage);

    this.speed = root.querySelector<HTMLInputElement>("[data-settings-speed]");
    this.size = root.querySelector<HTMLInputElement>("[data-settings-size]");
    this.offsetX = root.querySelector<HTMLInputElement>("[data-settings-offset-x]");
    this.offsetY = root.querySelector<HTMLInputElement>("[data-settings-offset-y]");
    this.theme = root.querySelector<HTMLSelectElement>("[data-settings-theme]");
    this.resetButton = root.querySelector<HTMLButtonElement>("[data-settings-reset]");
    this.speedOutput = root.querySelector<HTMLOutputElement>("[data-settings-speed-value]");
    this.sizeOutput = root.querySelector<HTMLOutputElement>("[data-settings-size-value]");
    this.offsetXOutput = root.querySelector<HTMLOutputElement>("[data-settings-offset-x-value]");
    this.offsetYOutput = root.querySelector<HTMLOutputElement>("[data-settings-offset-y-value]");

    this.syncInputs();
    this.bind();
    this.onChange?.(this.settings);
  }

  /** Текущие настройки (копия, чтобы страница не меняла состояние формы). */
  get settings(): StudentSettings {
    return { ...this.current };
  }

  /** Вернуть настройки по умолчанию и сохранить их. */
  reset(): void {
    this.update({ ...STUDENT_SETTINGS_DEFAULTS });
  }

  private bind(): void {
    const update = (): void => this.update(this.readInputs());
    for (const input of [this.speed, this.size, this.offsetX, this.offsetY]) {
      input?.addEventListener("input", update);
    }
    this.theme?.addEventListener("change", update);
    this.resetButton?.addEventListener("click", (event) => {
      event.preventDefault();
      this.reset();
    });
  }

  private readInputs(): StudentSettings {
    const value = (input: HTMLInputElement | null, fallback: number): number => {
      if (!input) return fallback;
      const parsed = Number.parseFloat(input.value);
      return Number.isFinite(parsed) ? parsed : fallback;
    };
    return normalizeStudentSettings({
      speed: value(this.speed, this.current.speed),
      size: value(this.size, this.current.size),
      offsetX: value(this.offsetX, this.current.offsetX),
      offsetY: value(this.offsetY, this.current.offsetY),
      theme: this.theme?.value ?? this.current.theme,
    });
  }

  private update(next: StudentSettings): void {
    this.current = saveStudentSettings(next, this.storage);
    this.syncInputs();
    this.onChange?.(this.settings);
  }

  /** Показать сохранённые значения в полях и подписях. */
  private syncInputs(): void {
    const settings = this.current;
    if (this.speed) this.speed.value = String(settings.speed);
    if (this.size) this.size.value = String(settings.size);
    if (this.offsetX) this.offsetX.value = String(settings.offsetX);
    if (this.offsetY) this.offsetY.value = String(settings.offsetY);
    if (this.theme) this.theme.value = settings.theme;
    if (this.speedOutput) this.speedOutput.textContent = `${settings.speed.toFixed(2)}x`;
    if (this.sizeOutput) this.sizeOutput.textContent = `${Math.round(settings.size * 100)}%`;
    if (this.offsetXOutput) this.offsetXOutput.textContent = `${settings.offsetX}%`;
    if (this.offsetYOutput) this.offsetYOutput.textContent = `${settings.offsetY}%`;
  }
}
