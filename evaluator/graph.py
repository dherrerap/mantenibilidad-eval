"""Measures on the import graph shared by several points: fan-in and cliques (strongly connected components).
"""
import sys


def fan_in(m):
    fi = {}
    for mod in m["graph"].get("modules", []):
        for d in mod["deps"]:
            if d["local"]:
                fi[d["to"]] = fi.get(d["to"], 0) + 1
    return fi


def cliques(m):
    """Cliques in DV8's sense: sets of files that reach each other through dependencies (strongly connected components
    of size ≥ 2), computed on the import graph. Compared against the cycles reported by dependency-cruiser."""
    g = {}
    for mod in m["graph"].get("modules", []):
        g.setdefault(mod["source"], set()).update(d["to"] for d in mod["deps"] if d["local"] and d["to"] != mod["source"])
    idx, low, onst, st, out, n = {}, {}, set(), [], [], [0]

    def sc(v):
        idx[v] = low[v] = n[0]; n[0] += 1; st.append(v); onst.add(v)
        for w in g.get(v, ()):
            if w not in idx:
                sc(w); low[v] = min(low[v], low[w])
            elif w in onst:
                low[v] = min(low[v], idx[w])
        if low[v] == idx[v]:
            comp = []
            while True:
                w = st.pop(); onst.discard(w); comp.append(w)
                if w == v: break
            if len(comp) > 1: out.append(sorted(comp))
    sys.setrecursionlimit(max(1000, 10 * len(g)))
    for v in list(g):
        if v not in idx: sc(v)
    return out
