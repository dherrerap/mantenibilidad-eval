// artifacts.mjs — Findings recorded for the missing complementary artifacts. Port of artifact_findings in evaluator/artifacts.py
// (the inventory, which reads the app's files, comes with the collectors).
import { get } from "../lib/py.mjs";

export function artifactFindings(m) {
  const out = [];
  for (const a of get(m, "artifacts") || []) {
    if (a.level !== "complementary" || a.present) continue;
    const sev = get(a, "absence") === "high_finding" ? "Critical" : "Marginal";
    out.push({ artifact: a.id, name: a.name, severity: sev, affected_points: a.feeds,
      note: "absence recorded as a finding" + (sev === "Critical" ? "; it is not treated as missing data" : a.feeds.length ? "; lowers the confidence of the affected points" : "; context for step 1 only") });
  }
  return out;
}
