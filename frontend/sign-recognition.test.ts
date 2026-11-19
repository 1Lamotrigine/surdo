import { readFile, readdir } from "node:fs/promises";
import { beforeAll, describe, expect, it } from "vitest";

import { decodeClip } from "./clip";
import { recognizeSign, referenceFromClip, type SignReference } from "./sign-recognition";

describe("isolated Slovo sign recognition", () => {
  let references: SignReference[];

  beforeAll(async () => {
    const folder = new URL("./sign-references/", import.meta.url);
    const files = (await readdir(folder)).filter((name) => name.endsWith(".json.gz"));
    references = await Promise.all(files.map(async (name) =>
      referenceFromClip(await decodeClip(await readFile(new URL(name, folder)))),
    ));
  });

  it("loads all bundled references and recognizes their trajectories after resampling", () => {
    expect(references.map((reference) => reference.text).sort()).toEqual(
      ["вопрос", "да", "плохо", "пока", "привет", "хорошо"],
    );
    for (const reference of references) {
      const slower = reference.frames.flatMap((frame) => [frame, frame]);
      expect(recognizeSign(slower, references)).toBe(reference.text);
    }
  });

  it("rejects short, untracked, out-of-range and ambiguous observations", () => {
    const { frames } = references[0];
    expect(recognizeSign(frames.slice(0, 4), references)).toBeNull();
    expect(recognizeSign(frames.map((frame) => ({ ...frame, hands: [null, null] })), references)).toBeNull();
    expect(recognizeSign(frames.map((frame) => ({
      ...frame, arms: frame.arms.map((value) => value + 10),
    })), references)).toBeNull();
    expect(recognizeSign(frames, [references[0], { frames, text: "другой жест" }])).toBeNull();
  });
});
