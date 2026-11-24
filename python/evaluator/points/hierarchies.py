"""Decision point *Hierarchies* (Modularity): C1 inheritance depth, C2 direct children of the project's own classes,
C3 Unhealthy Inheritance (DV8's rules applied to the import graph).
"""

from evaluator.common import RUBRIC
from evaluator.criteria import C, apply_manual


def unhealthy_inheritance_graph(m):
    """DV8's two rules for Unhealthy Inheritance Hierarchy, applied to the import graph and the project's own classes:
    (1) the parent's file imports a child's file; (2) a client file imports both the parent and a child. Returns the list of findings."""
    cls = m["ast"]["classes"]; byname = {c["name"]: c for c in cls}
    deps = {}
    for mod in m["graph"].get("modules", []):
        deps[mod["source"]] = {d["to"] for d in mod["deps"] if d["local"]}
    found = []
    for child in cls:
        parent = byname.get((child["extends"] or "").split(".")[-1])
        if not parent or parent["file"] == child["file"]:
            continue
        if child["file"] in deps.get(parent["file"], set()):
            found.append(f"parent {parent['name']} ({parent['file']}) imports its child {child['name']} ({child['file']})")
        for client, ds in deps.items():
            if client not in (parent["file"], child["file"]) and parent["file"] in ds and child["file"] in ds:
                found.append(f"{client} imports parent {parent['name']} and child {child['name']}")
    return found


def eval_hierarchies(m, manual, opts):
    T = RUBRIC["thresholds"]["hierarchies"]
    cls = m["ast"]["classes"]; byname = {c["name"]: c for c in cls}
    def depth(c, seen=()):
        if not c["extends"]:
            return 0
        parent = byname.get(c["extends"].split(".")[-1])
        return 1 + (depth(parent, seen + (c["name"],)) if parent and parent["name"] not in seen else 0)
    kids = {}  # direct children of the project's OWN classes: subclasses of Error or React.Component are not a hierarchy of the app
    for c in cls:
        parent = (c["extends"] or "").split(".")[-1]
        if parent in byname:
            kids[parent] = kids.get(parent, 0) + 1
    deep = [c for c in cls if depth(c) > T["depth_max"]]
    wide = [k for k, v in kids.items() if v > T["children_max"]]
    uih = (manual.get("dv8") or {}).get("unhealthy_inheritance")
    own = any((c["extends"] or "").split(".")[-1] in byname for c in cls)
    if not own:  # no class extends another class of the application: there is no hierarchy to evaluate, which is not "Meets"
        what = f"{len(cls)} classes, none extends another class of the application" if cls else "no classes"
        return {}, {"classes": len(cls), "applicable": False}, [], f"Not applicable: {what}; there is no inheritance hierarchy to evaluate.", None
    # from here on the app has its own hierarchy (so at least two classes)
    uih_src = "dv8" if uih is not None else "pending (DV8)"
    if uih is None and m["graph"].get("modules"):  # a graph: DV8 rules on the graph
        uih = len(unhealthy_inheritance_graph(m)); uih_src = "auto (DV8 rules on the graph)"
    c3_ok = None if uih is None else uih == 0
    crit = {"C1": C(not deep, "0 classes with depth > 7", len(deep)),
            "C2": C(not wide, "0 classes with > 10 direct children", len(wide)),
            "C3": C(c3_ok, "0 Unhealthy Inheritance patterns (DV8)", uih, source=uih_src)}
    apply_manual("hierarchies", crit, manual)
    return crit, {"classes": len(cls)}, [f"{c['file']}: {c['name']}" for c in deep[:5]], f"{len(cls)} classes; {len(deep)} too deep; {len(wide)} with too many children.", None
