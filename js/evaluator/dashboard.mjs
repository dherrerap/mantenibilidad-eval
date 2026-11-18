// dashboard.mjs — Maintainability risk dashboard (protocol step 10, Table 29): semaphore per subcharacteristic, heat map, hotspots,
// and its Markdown and HTML renderings. Port of evaluator/dashboard.py.
import { fixed, get, gfmt, num, sorted, str } from "../lib/py.mjs";
import { artifactFindings } from "./artifacts.mjs";
import { RUBRIC } from "./common.mjs";

const LEVEL_STATE = { Meets: "green", Partial: "yellow", Fails: "red" };
export const LIGHT = { green: "🟢", yellow: "🟡", red: "🔴", undecided: "⚪", not_evaluable: "▨", unrelated: "·" };

export function semaphoreState(score) {
  const T = RUBRIC.risk_dashboard.semaphore;
  return score >= T.green_min ? "green" : score >= T.yellow_min ? "yellow" : "red";
}

/** The N worst files by complexity, inter-layer violations and cyclic dependencies. */
export function hotspots(m) {
  const N = RUBRIC.risk_dashboard.hotspots_top_n, thr = RUBRIC.thresholds.cyclomatic.function_threshold;
  const cc = {};
  for (const f of m.ast.functions) if (!f.test) cc[f.file] = Math.max(cc[f.file] ?? 0, f.cc);
  const byWorst = (d) => sorted(Object.entries(d), ([k, v]) => [-v, k]).slice(0, N);
  const complexity = byWorst(cc).map(([k, v]) => ({ file: k, value: v, detail: `max cyclomatic complexity ${v}` + (v > thr ? ` (> ${str(thr)})` : "") }));
  const layers = get(m, "layers", {}), allowed = RUBRIC.default_layers.allowed, main = new Set(["presentation", "business", "data"]);
  const viol = {};
  for (const mod of get(m.graph, "modules", [])) {
    const a = get(layers, mod.source);
    for (const d of mod.deps) {
      const b = d.local ? get(layers, d.to) : null;
      if (main.has(a) && main.has(b) && a !== b && !allowed.some(([x, y]) => x === a && y === b)) viol[mod.source] = (viol[mod.source] ?? 0) + 1;
    }
  }
  const cyc = {};
  for (const c of get(m.graph, "cycles", [])) for (const n of c) cyc[n] = (cyc[n] ?? 0) + 1;
  const top = (d, label) => byWorst(d).map(([k, v]) => ({ file: k, value: v, detail: `${v} ${label}` }));
  return { complexity, layer_violations: top(viol, "violating dependencies"), cyclic_dependencies: top(cyc, "cycle(s)") };
}

export function riskDashboard(points, prof, m) {
  const subs = Object.keys(RUBRIC.subcharacteristic_weights);
  const cells = [];
  for (const p of points) {
    for (const s of subs) {
      let state, esc;
      if (!p.subcharacteristics.includes(s)) [state, esc] = ["unrelated", false];
      else if (!p.evaluable) [state, esc] = ["not_evaluable", false];
      else {
        state = get(LEVEL_STATE, p.level, "undecided");
        esc = p.severity === "Critical" && state !== "red";  // a Critical finding forces red
        if (esc) state = "red";
      }
      cells.push({ point: p.id, subcharacteristic: s, state, escalated: esc });
    }
  }
  const semaphore = {};
  for (const [s, v] of Object.entries(prof.subcharacteristics)) {
    const high = points.filter((p) => p.subcharacteristics.includes(s) && p.severity === "Critical").map((p) => p.id);
    const state = v.min === null ? "not_evaluable" : semaphoreState(num(v.min));  // worst case of the range
    const esc = high.length > 0 && state !== "red" && state !== "not_evaluable";
    semaphore[s] = { min: v.min, max: v.max, state: esc ? "red" : state, escalated: esc, high_severity_points: high,
      range_crosses_cutoff: v.min !== null && semaphoreState(num(v.min)) !== semaphoreState(num(v.max)) };
  }
  return { semaphore, heatmap: cells, not_evaluable: points.filter((p) => !p.evaluable).map((p) => ({ point: p.id, name: p.name, missing: p.missing_artifacts })),
    artifact_findings: artifactFindings(m), hotspots: hotspots(m), thresholds: RUBRIC.risk_dashboard.semaphore };
}

export const fmtScore = (v) => (v.min === null ? "n/a" : num(v.min) === num(v.max) ? fixed(v.min, 1) : `${fixed(v.min, 1)}–${fixed(v.max, 1)}`);

export function dashboardMarkdown(d, points) {
  const names = points.map((p) => [p.id, p.name]);
  const subs = Object.keys(d.semaphore), T = d.thresholds;
  const L = ["## Risk dashboard", "",
    `🟢 ≥ ${gfmt(T.green_min)} · 🟡 ≥ ${gfmt(T.yellow_min)} · 🔴 below (weighted subcharacteristic score, worst case of the range). ` +
    "Heat map: 🟢 Meets · 🟡 Partial · 🔴 Fails · ⚪ undecided · ▨ not evaluable · · not related. A high-severity finding forces red (marked ↑).", "",
    "### Semaphore per subcharacteristic", "", "| Subcharacteristic | Score | | Note |", "|---|---|---|---|"];
  for (const [s, v] of Object.entries(d.semaphore)) {
    const note = v.escalated ? "forced red by high severity: " + v.high_severity_points.join(", ") : v.state === "not_evaluable" ? "not evaluable" : v.range_crosses_cutoff ? "range crosses a cut-off" : "";
    L.push(`| ${s} | ${fmtScore(v)} | ${LIGHT[v.state]} | ${note} |`);
  }
  L.push("", "### Heat map: decision points × subcharacteristics", "", "| Decision point | " + subs.join(" | ") + " |", "|---|" + "---|".repeat(subs.length));
  for (const [pid, name] of uniqueIds(names)) {
    const row = subs.map((s) => {
      const c = d.heatmap.find((x) => x.point === pid && x.subcharacteristic === s);
      return LIGHT[c.state] + (c.escalated ? " ↑" : "") + (c.state === "not_evaluable" ? " not evaluable" : "");
    });
    L.push(`| ${name} | ` + row.join(" | ") + " |");
  }
  if (d.not_evaluable.length) L.push("", "### Not evaluable (no evidence)", "", ...d.not_evaluable.map((x) => `- ▨ **${x.name}**: missing ${x.missing.join(", ")}`));
  if (d.artifact_findings.length)
    L.push("", "### Findings from missing artifacts", "", ...d.artifact_findings.map((f) => `- **${f.severity}** — ${f.name}: ${f.note} (affects: ${f.affected_points.join(", ") || "step 1 context"})`));
  const hs = d.hotspots;
  if (Object.values(hs).some((v) => v.length)) {
    L.push("", "### Module hotspots (automatable indicators only)", "");
    for (const [key, title] of [["complexity", "Complexity"], ["layer_violations", "Layer violations"], ["cyclic_dependencies", "Cyclic dependencies"]])
      if (hs[key].length) L.push(`- **${title}:** ` + hs[key].map((x) => `\`${x.file}\` (${x.detail})`).join("; "));
  }
  return [...L, ""];
}

/** {id: name} of the points, in order, one entry per id (a dict in Python: a repeated id keeps its first place and its last name). */
function uniqueIds(pairs) {
  const m = new Map();
  for (const [k, v] of pairs) m.set(k, v);
  return [...m];
}

const HTML_STYLE = `body{font:15px system-ui,sans-serif;margin:24px;max-width:960px} table{border-collapse:collapse;width:100%} th,td{border:1px solid #bbb;padding:8px;text-align:center} th{text-align:left}
.green{background:#2e9e5b;color:#fff} .yellow{background:#f2c230;color:#222} .red{background:#d64545;color:#fff} .undecided{background:#fff;color:#555} .unrelated{background:#e6e6e6}
.not_evaluable{background:repeating-linear-gradient(45deg,#d9d9d9,#d9d9d9 6px,#f4f4f4 6px,#f4f4f4 12px);color:#333;font-style:italic}
.cards{display:flex;gap:12px;flex-wrap:wrap;margin:16px 0} .card{flex:1 1 180px;padding:12px;border-radius:8px;border:1px solid #bbb} .card span{display:block;font-size:26px;margin-top:4px} small{display:block}`;

const CELL_LABEL = { green: "Meets", yellow: "Partial", red: "Fails", undecided: "undecided", not_evaluable: "not evaluable", unrelated: "" };

export function dashboardHtml(d, points, title) {
  const subs = Object.keys(d.semaphore);
  const esc = (t) => str(t).replaceAll("&", "&amp;").replaceAll("<", "&lt;");
  let rows = "";
  for (const [pid, name] of uniqueIds(points.map((p) => [p.id, p.name]))) {
    rows += `<tr><th>${esc(name)}</th>`;
    for (const s of subs) {
      const c = d.heatmap.find((x) => x.point === pid && x.subcharacteristic === s);
      rows += `<td class="${c.state}">${CELL_LABEL[c.state]}${c.escalated ? " ↑" : ""}</td>`;
    }
    rows += "</tr>";
  }
  const cards = Object.entries(d.semaphore).map(([s, v]) => `<div class="card ${v.state}"><b>${esc(s)}</b><span>${fmtScore(v)}</span>${v.escalated ? "<small>forced red: high severity</small>" : ""}</div>`).join("");
  const titles = [["complexity", "Complexity"], ["layer_violations", "Layer violations"], ["cyclic_dependencies", "Cyclic dependencies"]];
  const hs = titles.filter(([k]) => d.hotspots[k].length).map(([k, t]) => `<h3>${t}</h3><ul>` + d.hotspots[k].map((x) => `<li><code>${esc(x.file)}</code> — ${esc(x.detail)}</li>`).join("") + "</ul>").join("");
  const ne = d.not_evaluable.map((x) => `<li>${esc(x.name)}: missing ${esc(x.missing.join(", "))}</li>`).join("");
  const af = d.artifact_findings.map((f) => `<li><b>${f.severity}</b> — ${esc(f.name)}</li>`).join("");
  const head = subs.map((s) => `<th>${esc(s)}</th>`).join("");
  const T = d.thresholds;
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">` +
    `<title>${esc(title)}</title><style>${HTML_STYLE}</style></head><body><h1>${esc(title)}</h1>` +
    `<p>Semaphore: green ≥ ${gfmt(T.green_min)}, yellow ≥ ${gfmt(T.yellow_min)}, red below (worst case of the score range). A high-severity finding forces red (↑).</p>` +
    `<div class="cards">${cards}</div><table><tr><th>Decision point</th>${head}</tr>${rows}</table>` +
    (ne ? `<h2>Not evaluable</h2><ul>${ne}</ul>` : "") + (af ? `<h2>Findings from missing artifacts</h2><ul>${af}</ul>` : "") +
    (hs ? `<h2>Module hotspots</h2>${hs}` : "") + "</body></html>\n";
}
