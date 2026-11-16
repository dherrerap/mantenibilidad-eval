"""Maintainability risk dashboard (protocol step 10, Table 29): semaphore per subcharacteristic, heat map, hotspots, and its
Markdown and HTML renderings.
"""

from evaluator.artifacts import artifact_findings
from evaluator.common import RUBRIC


LEVEL_STATE = {"Meets": "green", "Partial": "yellow", "Fails": "red"}


LIGHT = {"green": "🟢", "yellow": "🟡", "red": "🔴", "undecided": "⚪", "not_evaluable": "▨", "unrelated": "·"}


def semaphore_state(score):
    """Table 29, semaphore per subcharacteristic: cut-offs from rubric.json (risk_dashboard.semaphore)."""
    T = RUBRIC["risk_dashboard"]["semaphore"]
    return "green" if score >= T["green_min"] else ("yellow" if score >= T["yellow_min"] else "red")


def hotspots(m):
    """Optional module hotspots, from automatable indicators only: the N worst files by complexity,
    inter-layer violations and cyclic dependencies."""
    N = RUBRIC["risk_dashboard"]["hotspots_top_n"]
    thr = RUBRIC["thresholds"]["cyclomatic"]["function_threshold"]
    cc = {}
    for f in m["ast"]["functions"]:
        if not f["test"]:
            cc[f["file"]] = max(cc.get(f["file"], 0), f["cc"])
    complexity = [{"file": k, "value": v, "detail": f"max cyclomatic complexity {v}" + (f" (> {thr})" if v > thr else "")}
                  for k, v in sorted(cc.items(), key=lambda kv: (-kv[1], kv[0]))[:N]]
    layers = m.get("layers", {}); allowed = RUBRIC["default_layers"]["allowed"]; main = {"presentation", "business", "data"}
    viol = {}
    for mod in m["graph"].get("modules", []):
        a = layers.get(mod["source"])
        for d in mod["deps"]:
            b = layers.get(d["to"]) if d["local"] else None
            if a in main and b in main and a != b and [a, b] not in allowed:
                viol[mod["source"]] = viol.get(mod["source"], 0) + 1
    cyc = {}
    for c in m["graph"].get("cycles", []):
        for n in c:
            cyc[n] = cyc.get(n, 0) + 1
    top = lambda d, label: [{"file": k, "value": v, "detail": f"{v} {label}"} for k, v in sorted(d.items(), key=lambda kv: (-kv[1], kv[0]))[:N]]
    return {"complexity": complexity, "layer_violations": top(viol, "violating dependencies"), "cyclic_dependencies": top(cyc, "cycle(s)")}


def risk_dashboard(points, prof, m):
    """Steps 9-10 / Table 29: semaphore per subcharacteristic, points × subcharacteristics heat map, escalation of
    high-severity findings, points not evaluable for lack of evidence, and (optional) module hotspots."""
    subs = list(RUBRIC["subcharacteristic_weights"])
    cells = []
    for p in points:
        for s in subs:
            if s not in p["subcharacteristics"]:
                state, esc = "unrelated", False  # not related in Table 24
            elif not p["evaluable"]:
                state, esc = "not_evaluable", False  # distinct from "Meets"
            else:
                state = LEVEL_STATE.get(p["level"], "undecided")
                esc = p["severity"] == "Critical" and state != "red"  # a Critical finding forces red
                state = "red" if esc else state
            cells.append({"point": p["id"], "subcharacteristic": s, "state": state, "escalated": esc})
    semaphore = {}
    for s, v in prof["subcharacteristics"].items():
        high = [p["id"] for p in points if s in p["subcharacteristics"] and p["severity"] == "Critical"]
        state = "not_evaluable" if v["min"] is None else semaphore_state(v["min"])  # worst case of the range
        esc = bool(high) and state not in ("red", "not_evaluable")
        semaphore[s] = {"min": v["min"], "max": v["max"], "state": "red" if esc else state, "escalated": esc, "high_severity_points": high,
                        "range_crosses_cutoff": v["min"] is not None and semaphore_state(v["min"]) != semaphore_state(v["max"])}
    return {"semaphore": semaphore, "heatmap": cells,
            "not_evaluable": [{"point": p["id"], "name": p["name"], "missing": p["missing_artifacts"]} for p in points if not p["evaluable"]],
            "artifact_findings": artifact_findings(m), "hotspots": hotspots(m),
            "thresholds": RUBRIC["risk_dashboard"]["semaphore"]}


def fmt_score(v):
    return "n/a" if v["min"] is None else (f"{v['min']:.1f}" if v["min"] == v["max"] else f"{v['min']:.1f}–{v['max']:.1f}")


def dashboard_markdown(d, points):
    names = {p["id"]: p["name"] for p in points}
    subs = list(d["semaphore"])
    T = d["thresholds"]
    L = ["## Risk dashboard", "",
         f"🟢 ≥ {T['green_min']:g} · 🟡 ≥ {T['yellow_min']:g} · 🔴 below (weighted subcharacteristic score, worst case of the range). "
         "Heat map: 🟢 Meets · 🟡 Partial · 🔴 Fails · ⚪ undecided · ▨ not evaluable · · not related. "
         "A high-severity finding forces red (marked ↑).", "",
         "### Semaphore per subcharacteristic", "", "| Subcharacteristic | Score | | Note |", "|---|---|---|---|"]
    for s, v in d["semaphore"].items():
        note = ("forced red by high severity: " + ", ".join(v["high_severity_points"])) if v["escalated"] else ("not evaluable" if v["state"] == "not_evaluable" else ("range crosses a cut-off" if v["range_crosses_cutoff"] else ""))
        L.append(f"| {s} | {fmt_score(v)} | {LIGHT[v['state']]} | {note} |")
    L += ["", "### Heat map: decision points × subcharacteristics", "", "| Decision point | " + " | ".join(subs) + " |", "|---|" + "---|" * len(subs)]
    for pid, name in names.items():
        row = []
        for s in subs:
            c = next(x for x in d["heatmap"] if x["point"] == pid and x["subcharacteristic"] == s)
            row.append(LIGHT[c["state"]] + (" ↑" if c["escalated"] else "") + (" not evaluable" if c["state"] == "not_evaluable" else ""))
        L.append(f"| {name} | " + " | ".join(row) + " |")
    if d["not_evaluable"]:
        L += ["", "### Not evaluable (no evidence)", ""] + [f"- ▨ **{x['name']}**: missing {', '.join(x['missing'])}" for x in d["not_evaluable"]]
    if d["artifact_findings"]:
        L += ["", "### Findings from missing artifacts", ""] + [f"- **{f['severity']}** — {f['name']}: {f['note']} (affects: {', '.join(f['affected_points']) or 'step 1 context'})" for f in d["artifact_findings"]]
    hs = d["hotspots"]
    if any(hs.values()):
        L += ["", "### Module hotspots (automatable indicators only)", ""]
        for key, title in (("complexity", "Complexity"), ("layer_violations", "Layer violations"), ("cyclic_dependencies", "Cyclic dependencies")):
            if hs[key]:
                L.append(f"- **{title}:** " + "; ".join(f"`{x['file']}` ({x['detail']})" for x in hs[key]))
    return L + [""]


HTML_STYLE = """body{font:15px system-ui,sans-serif;margin:24px;max-width:960px} table{border-collapse:collapse;width:100%} th,td{border:1px solid #bbb;padding:8px;text-align:center} th{text-align:left}
.green{background:#2e9e5b;color:#fff} .yellow{background:#f2c230;color:#222} .red{background:#d64545;color:#fff} .undecided{background:#fff;color:#555} .unrelated{background:#e6e6e6}
.not_evaluable{background:repeating-linear-gradient(45deg,#d9d9d9,#d9d9d9 6px,#f4f4f4 6px,#f4f4f4 12px);color:#333;font-style:italic}
.cards{display:flex;gap:12px;flex-wrap:wrap;margin:16px 0} .card{flex:1 1 180px;padding:12px;border-radius:8px;border:1px solid #bbb} .card span{display:block;font-size:26px;margin-top:4px} small{display:block}"""


CELL_LABEL = {"green": "Meets", "yellow": "Partial", "red": "Fails", "undecided": "undecided", "not_evaluable": "not evaluable", "unrelated": ""}


def dashboard_html(d, points, title):
    names = {p["id"]: p["name"] for p in points}
    subs = list(d["semaphore"])
    esc = lambda t: str(t).replace("&", "&amp;").replace("<", "&lt;")
    rows = ""
    for pid, name in names.items():
        rows += f"<tr><th>{esc(name)}</th>"
        for s in subs:
            c = next(x for x in d["heatmap"] if x["point"] == pid and x["subcharacteristic"] == s)
            rows += f'<td class="{c["state"]}">{CELL_LABEL[c["state"]]}{" ↑" if c["escalated"] else ""}</td>'
        rows += "</tr>"
    cards = "".join(f'<div class="card {v["state"]}"><b>{esc(s)}</b><span>{fmt_score(v)}</span>{"<small>forced red: high severity</small>" if v["escalated"] else ""}</div>'
                    for s, v in d["semaphore"].items())
    titles = (("complexity", "Complexity"), ("layer_violations", "Layer violations"), ("cyclic_dependencies", "Cyclic dependencies"))
    hs = "".join(f"<h3>{t}</h3><ul>" + "".join(f"<li><code>{esc(x['file'])}</code> — {esc(x['detail'])}</li>" for x in d["hotspots"][k]) + "</ul>" for k, t in titles if d["hotspots"][k])
    ne = "".join(f"<li>{esc(x['name'])}: missing {esc(', '.join(x['missing']))}</li>" for x in d["not_evaluable"])
    af = "".join(f"<li><b>{f['severity']}</b> — {esc(f['name'])}</li>" for f in d["artifact_findings"])
    head = "".join(f"<th>{esc(s)}</th>" for s in subs)
    T = d["thresholds"]
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>{esc(title)}</title><style>{HTML_STYLE}</style></head><body><h1>{esc(title)}</h1>"
            f"<p>Semaphore: green ≥ {T['green_min']:g}, yellow ≥ {T['yellow_min']:g}, red below (worst case of the score range). A high-severity finding forces red (↑).</p>"
            f'<div class="cards">{cards}</div><table><tr><th>Decision point</th>{head}</tr>{rows}</table>'
            + (f"<h2>Not evaluable</h2><ul>{ne}</ul>" if ne else "") + (f"<h2>Findings from missing artifacts</h2><ul>{af}</ul>" if af else "")
            + (f"<h2>Module hotspots</h2>{hs}" if hs else "") + "</body></html>\n")
