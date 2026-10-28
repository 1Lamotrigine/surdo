/**
 * Лента расшифровки (C8): прочитанные фразы одной прокручиваемой лентой.
 *
 * Субтитр (`subtitles.ts`) показывает **одну текущую** фразу: как только
 * преподаватель говорит следующую, предыдущий текст исчезает, и студент не
 * может перечитать пропущенное. Лента решает это: каждая распознанная фраза
 * добавляется в конец списка, старые остаются выше и доступны прокруткой.
 *
 * Здесь живёт **чистая** часть: предел ленты, отбор дублей по `seq`, выбор
 * видной строки и решение «прокручивать ли вниз» (не дёргать ленту, если
 * студент читает выше). DOM-слой `TranscriptView` только рисует строки.
 *
 * Лента только для чтения: подсветка слова в ней не идёт (она в субтитрах).
 */

/** Одна строка ленты: распознанный текст и его порядковый номер. */
export type TranscriptLine = {
  /** Порядковый номер фразы в комнате (`Utterance.seq`), 0 — без номера. */
  seq: number;
  /** Распознанный текст фразы. */
  text: string;
};

/** Сколько строк держим в ленте: старые вытесняются сверху. */
export const TRANSCRIPT_MAX_LINES = 200;

/** Текст для строки: обрезаем пробелы; пустое не показываем. */
export function transcriptText(text: string): string {
  return (text ?? "").replace(/\s+/gu, " ").trim();
}

/**
 * Добавить строку в конец ленты по правилам дублей и предела.
 *
 * Фраза с уже известным `seq` (0 < seq ≤ последнего) не добавляется: события
 * `asr_text` и `utterance` описывают одну и ту же фразу, и переподключение
 * может прислать её повторно. `asr_text` приходит раньше и без `seq` (0):
 * такая строка заменяет последнюю строку без номера, а не плодит дубли.
 */
export function appendTranscript(
  lines: TranscriptLine[],
  line: TranscriptLine,
  max = TRANSCRIPT_MAX_LINES,
): TranscriptLine[] {
  const text = transcriptText(line.text);
  if (!text) return lines;

  const seq = Number.isFinite(line.seq) ? Math.max(0, Math.trunc(line.seq)) : 0;

  if (seq > 0) {
    const lastSeq = lastKnownSeq(lines);
    if (seq <= lastSeq) return lines;
    return capTranscript([...lines, { seq, text }], max);
  }

  // Без номера: либо заменяем такую же последнюю строку, либо добавляем.
  const last = lines[lines.length - 1];
  if (last && last.seq === 0) {
    return capTranscript([...lines.slice(0, -1), { seq: 0, text }], max);
  }
  return capTranscript([...lines, { seq: 0, text }], max);
}

/** Наибольший известный `seq` среди строк (0, если номеров нет). */
export function lastKnownSeq(lines: TranscriptLine[]): number {
  let last = 0;
  for (const line of lines) {
    if (line.seq > last) last = line.seq;
  }
  return last;
}

/** Оставить не больше `max` последних строк. */
function capTranscript(lines: TranscriptLine[], max: number): TranscriptLine[] {
  if (max <= 0) return [];
  return lines.length > max ? lines.slice(lines.length - max) : lines;
}

/**
 * Нужно ли прокрутить ленту вниз после добавления строки.
 *
 * Если студент пролистал вверх и читает ранее сказанное, дёргать ленту нельзя:
 * иначе новая фраза утащит его вниз. Допуск (по умолчанию 48 px) — «почти внизу».
 */
export function shouldStickToBottom(
  metrics: { scrollTop: number; scrollHeight: number; clientHeight: number },
  tolerance = 48,
): boolean {
  const distance = metrics.scrollHeight - metrics.scrollTop - metrics.clientHeight;
  return distance <= Math.max(0, tolerance);
}

/** Пустая лента: подпись, пока не пришла ни одна фраза. */
export const TRANSCRIPT_EMPTY_HINT = "Расшифровка появится, когда преподаватель заговорит.";

/**
 * Лента расшифровки в DOM: список фраз под аватаром.
 *
 * Строки только добавляются (свежие снизу) и вытесняются по пределу. Прокрутка
 * вниз — только если студент и так внизу (`shouldStickToBottom`), чтобы чтение
 * выше не прерывалось. Класс `transcript-line-current` отмечает последнюю
 * фразу: её же показывает субтитр.
 */
export class TranscriptView {
  private readonly root: HTMLElement;
  private readonly list: HTMLElement;
  private readonly empty: HTMLElement;
  private readonly maxLines: number;
  private lines: TranscriptLine[] = [];

  constructor(root: HTMLElement, options: { maxLines?: number } = {}) {
    this.root = root;
    this.maxLines = options.maxLines ?? TRANSCRIPT_MAX_LINES;

    this.empty = document.createElement("p");
    this.empty.className = "transcript-empty";
    this.empty.textContent = TRANSCRIPT_EMPTY_HINT;

    this.list = document.createElement("ol");
    this.list.className = "transcript-list";

    this.root.replaceChildren(this.empty, this.list);
    this.root.classList.add("transcript");
  }

  /** Добавить фразу: дубли по `seq` и предел обрабатывает `appendTranscript`. */
  push(line: TranscriptLine): void {
    const before = this.lines;
    this.lines = appendTranscript(this.lines, line, this.maxLines);
    if (this.lines === before) return;

    this.render();
  }

  /** Заменить всё содержимое (например, после переподключения). */
  replace(lines: TranscriptLine[]): void {
    this.lines = [];
    for (const line of lines) {
      this.lines = appendTranscript(this.lines, line, this.maxLines);
    }
    this.render(true);
  }

  /** Текущий текст ленты (для тестов и синхронизации). */
  getLines(): TranscriptLine[] {
    return [...this.lines];
  }

  private render(force = false): void {
    const stick = force || shouldStickToBottom(this.root);

    this.empty.hidden = this.lines.length > 0;
    this.list.replaceChildren(
      ...this.lines.map((line, index) => this.renderLine(line, index)),
    );

    if (stick) this.root.scrollTop = this.root.scrollHeight;
  }

  private renderLine(line: TranscriptLine, index: number): HTMLElement {
    const item = document.createElement("li");
    item.className = "transcript-line";
    if (index === this.lines.length - 1) {
      item.classList.add("transcript-line-current");
    }
    if (line.seq > 0) item.dataset.seq = String(line.seq);
    item.textContent = line.text;
    return item;
  }
}
