// Run from app with node scripts/build-sign-library.mjs after updating assets/slovo.
import { readFile, readdir, writeFile } from "node:fs/promises";
import { gzipSync } from "node:zlib";
import { createServer } from "vite";

const server = await createServer({ server: { middlewareMode: true, hmr: false } });
try {
  const { decodeClip } = await server.ssrLoadModule("/frontend/clip.ts");
  const { referenceFromClip } = await server.ssrLoadModule("/frontend/sign-recognition.ts");
  const references = [];
  for (const file of (await readdir("assets/slovo/clips")).sort()) {
    const clip = await decodeClip(await readFile("assets/slovo/clips/" + file));
    try {
      references.push(referenceFromClip(clip));
    } catch (error) {
      console.warn(file, error.message);
    }
  }
  const json = JSON.stringify(references, (_, value) =>
    typeof value === "number" ? Math.round(value * 100) / 100 : value);
  await writeFile("frontend/sign-references/library.gz", gzipSync(json));
} finally {
  await server.close();
}
