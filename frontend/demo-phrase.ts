/**
 * Синтетическая фраза с субтитрами для тестовой страницы (C6).
 *
 * В репозитории нет записанных жестов (их пишет блок D) и нет сервера глосс (блок
 * E), поэтому демонстрация субтитров собирается в браузере: фраза из токенов
 * глосс (ТЗ 7.2) + синтетический клип на каждую единицу показа (жест, число,
 * буква дактиля). Субтитр подсвечивает слово по текущему клипу очереди.
 */

import { DACTYL_ALPHABET } from "./dactyl";
import { encodeDactylClip, encodeDemoClip } from "./demo-clip";
import { utteranceUnits, type UtteranceGlosses } from "./subtitles";

/** Фраза-пример: жесты, число и слово по буквам. */
export const DEMO_PHRASE: UtteranceGlosses = {
  text: "Откройте учебник на странице десять Иванов",
  lang: "rsl",
  sentence_type: "imperative",
  tokens: [
    { type: "sign", gloss: "ОТКРЫТЬ", src: "Откройте" },
    { type: "sign", gloss: "УЧЕБНИК", src: "учебник" },
    { type: "sign", gloss: "СТРАНИЦА", src: "странице" },
    { type: "number", value: 10, src: "десять" },
    { type: "fingerspell", letters: ["И", "В", "А", "Н", "О", "В"], src: "Иванов" },
  ],
};

/** Варианты синтетического жеста для жестовых единиц (чтобы отличались). */
const SIGN_VARIANTS = [0, 1, 2];

/**
 * Собрать клипы для фразы: по одному на единицу показа. Жесты — синтетические
 * варианты, буквы дактиля — синтетические буквы. Порядок совпадает с
 * `utteranceUnits(DEMO_PHRASE)`.
 */
export async function encodePhraseClips(
  utterance: UtteranceGlosses = DEMO_PHRASE,
): Promise<Record<string, unknown>[]> {
  const units = utteranceUnits(utterance);
  let signIndex = 0;
  return Promise.all(
    units.map((unit) => {
      if (unit.kind === "fingerspell") {
        const letter = unit.gloss.replace(/^ДАКТИЛЬ_/, "");
        return encodeDactylClip(letter, DACTYL_ALPHABET);
      }
      const variant = SIGN_VARIANTS[signIndex % SIGN_VARIANTS.length];
      signIndex += 1;
      return encodeDemoClip(30, 30, variant);
    }),
  );
}
