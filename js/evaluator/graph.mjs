// graph.mjs — Measures on the import graph shared by several points: fan-in and cliques. Port of evaluator/graph.py.
import { get, sorted } from "../lib/py.mjs";

export function fanIn(m) {
  const fi = {};
  for (const mod of get(m.graph, "modules", [])) for (const d of mod.deps) if (d.local) fi[d.to] = (fi[d.to] ?? 0) + 1;
  return fi;
}

/** Cliques in DV8's sense: strongly connected components of size ≥ 2 of the import graph (Tarjan), neighbours in import order. */
export function cliques(m) {
  const g = new Map();
  for (const mod of get(m.graph, "modules", [])) {
    if (!g.has(mod.source)) g.set(mod.source, new Set());
    for (const d of mod.deps) if (d.local && d.to !== mod.source) g.get(mod.source).add(d.to);  // a JS Set keeps insertion order
  }
  const idx = new Map(), low = new Map(), onst = new Set(), st = [], out = [];
  let n = 0;
  const sc = (v) => {
    idx.set(v, n); low.set(v, n); n += 1; st.push(v); onst.add(v);
    for (const w of g.get(v) ?? []) {
      if (!idx.has(w)) { sc(w); low.set(v, Math.min(low.get(v), low.get(w))); }
      else if (onst.has(w)) low.set(v, Math.min(low.get(v), idx.get(w)));
    }
    if (low.get(v) === idx.get(v)) {
      const comp = [];
      for (;;) {
        const w = st.pop(); onst.delete(w); comp.push(w);
        if (w === v) break;
      }
      if (comp.length > 1) out.push(sorted(comp));
    }
  };
  for (const v of [...g.keys()]) if (!idx.has(v)) sc(v);
  return out;
}
