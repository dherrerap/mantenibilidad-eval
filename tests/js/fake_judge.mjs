// A stand-in for the judge model in the differential tests. It reads the prompt on stdin and answers every criterion the prompt asks
// for with a decision derived from the SHA-256 of the prompt and from how many times that prompt was asked before. The count is kept
// in the folder FAKE_JUDGE_STATE. Python's judge.py and the JavaScript port therefore get the same answers only if they send exactly
// the same prompts, in the same order. The votes of one criterion vary, so non-unanimous decisions and "I don't know" votes occur.
import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";

let prompt = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (c) => { prompt += c; });
process.stdin.on("end", () => {
  prompt = prompt.replaceAll("\r\n", "\n");  // Python on Windows writes the prompt to stdin in text mode, with CRLF
  const hex = createHash("sha256").update(prompt, "utf8").digest("hex");
  let n = 0;
  const state = process.env.FAKE_JUDGE_STATE;
  if (state) {
    fs.mkdirSync(state, { recursive: true });
    const f = path.join(state, hex.slice(0, 16));
    n = fs.existsSync(f) ? Number(fs.readFileSync(f, "utf8")) : 0;
    fs.writeFileSync(f, String(n + 1));
  }
  const h = createHash("sha256").update(`${hex}:${n}`).digest();
  const cids = [...prompt.matchAll(/^- [a-z_]+\.(C\d+):/gm)].map((m) => m[1]);
  const out = {};
  cids.forEach((c, i) => {
    const b = h[i % h.length];
    out[c] = { ok: b % 5 === 0 ? null : b % 2 === 0, justification: `fake ${c} vote ${n}`, confidence: ["high", "medium", "low"][b % 3] };
  });
  process.stdout.write("Here is my answer: " + JSON.stringify(out) + "\n");
});
