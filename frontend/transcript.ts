/**
 * Лента расшифровки (C8): прочитанные фразы одной прокручиваемой лентой.
 *
 * Субтитр (`subtitles.ts`) показывает **одну текущую** фразу: как только
 * преподаватель говорит следующую, предыдущий текст исчезает, и студент не
 * может перечитать пропущенное. Лента решает это: каждая распознанная фраза
 * добавляется **сверху**, поэтому свежее сказанное всегда первое, а старое
 * уходит вниз и доступно прокруткой.
 *
 * Здесь живёт **чистая** часть: предел ленты, отбор дублей по `seq`, выбор
 * видной строки и решение «прокручивать ли наверх» (не дёргать ленту, если
 * студент читает ниже). DOM-слой `TranscriptView` только рисует строки.
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

/** Сколько строк держим в ленте: самые старые вытесняются снизу. */
export const TRANSCRIPT_MAX_LINES = 200;

/** Текст для строки: обрезаем пробелы; пустое не показываем. */
export function transcriptText(text: string): string {
  return (text ?? "").replace(/\s+/gu, " ").trim();
}

/**
 * Добавить строку **в начало** ленты по правилам дублей и предела.
 *
 * Свежая фраза идёт первой (сверху), старые сдвигаются вниз. Фраза с уже
 * известным `seq` (0 < seq ≤ максимального) не добавляется: события `asr_text`
 * и `utterance` описывают одну и ту же фразу, и переподключение может прислать
 * её повторно. `asr_text` приходит раньше и без `seq` (0): такая строка
 * заменяет первую строку без номера, а не плодит дубли.
 */
export function prependTranscript(
  lines: TranscriptLine[],
  line: TranscriptLine,
  max = TRANSCRIPT_MAX_LINES,
): TranscriptLine[] {
  const text = transcriptText(line.text);
  if (!text) return lines;

  const seq = Number.isFinite(line.seq) ? Math.max(0, Math.trunc(line.seq)) : 0;

  if (seq > 0) {
    if (seq <= lastKnownSeq(lines)) return lines;
    // `asr_text` уже показал эту же фразу без номера. Финализированная
    // `utterance` (её текст может быть сжат по F8) заменяет черновую строку,
    // а не добавляет вторую копию той же фразы.
    const rest = lines[0]?.seq === 0 ? lines.slice(1) : lines;
    return capTranscript([{ seq, text }, ...rest], max);
  }

  // Без номера: либо заменяем первую такую же строку, либо добавляем сверху.
  const first = lines[0];
  if (first && first.seq === 0) {
    return capTranscript([{ seq: 0, text }, ...lines.slice(1)], max);
  }
  return capTranscript([{ seq: 0, text }, ...lines], max);
}

/** Наибольший известный `seq` среди строк (0, если номеров нет). */
export function lastKnownSeq(lines: TranscriptLine[]): number {
  let last = 0;
  for (const line of lines) {
    if (line.seq > last) last = line.seq;
  }
  return last;
}

/** Оставить не больше `max` свежих строк: старые (в конце) отбрасываются. */
function capTranscript(lines: TranscriptLine[], max: number): TranscriptLine[] {
  if (max <= 0) return [];
  return lines.length > max ? lines.slice(0, max) : lines;
}

/**
 * Нужно ли прокрутить ленту наверх после добавления строки.
 *
 * Если студент пролистал вниз и читает ранее сказанное, дёргать ленту нельзя:
 * иначе новая фраза утащит его наверх. Допуск (по умолчанию 48 px) — «почти
 * наверху».
 */
export function shouldStickToTop(
  metrics: { scrollTop: number; scrollHeight: number; clientHeight: number },
  tolerance = 48,
): boolean {
  return metrics.scrollTop <= Math.max(0, tolerance);
}

/** Пустая лента: подпись, пока не пришла ни одна фраза. */
export const TRANSCRIPT_EMPTY_HINT = "Расшифровка появится, когда преподаватель заговорит.";

/**
 * Лента расшифровки в DOM: список фраз под аватаром.
 *
 * Строки только добавляются (свежие сверху) и вытесняются по пределу. Прокрутка
 * наверх — только если студент и так наверху (`shouldStickToTop`), чтобы чтение
 * ниже не прерывалось. Класс `transcript-line-current` отмечает свежую фразу:
 * её же показывает субтитр.
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

  /** Добавить фразу: дубли по `seq` и предел обрабатывает `prependTranscript`. */
  push(line: TranscriptLine): void {
    const before = this.lines;
    this.lines = prependTranscript(this.lines, line, this.maxLines);
    if (this.lines === before) return;

    this.render();
  }

  /** Заменить всё содержимое (например, после переподключения). */
  replace(lines: TranscriptLine[]): void {
    this.lines = [];
    for (const line of lines) {
      this.lines = prependTranscript(this.lines, line, this.maxLines);
    }
    this.render(true);
  }

  /** Текущий текст ленты (для тестов и синхронизации). */
  getLines(): TranscriptLine[] {
    return [...this.lines];
  }

  private render(force = false): void {
    const stick = force || shouldStickToTop(this.root);

    this.empty.hidden = this.lines.length > 0;
    this.list.replaceChildren(
      ...this.lines.map((line, index) => this.renderLine(line, index)),
    );

    if (stick) this.root.scrollTop = 0;
  }

  private renderLine(line: TranscriptLine, index: number): HTMLElement {
    const item = document.createElement("li");
    item.className = "transcript-line";
    if (index === 0) {
      item.classList.add("transcript-line-current");
    }
    if (line.seq > 0) item.dataset.seq = String(line.seq);
    item.textContent = line.text;
    return item;
  }
}
