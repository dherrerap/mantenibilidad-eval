"""Decision point *Data model design* (Modularity, Analyzability): C1-C6 over the relational schema (static or the live
database): keys, normalization (heuristic), constraints, indexes, type consistency (heuristic) and the ER model.
"""
import re

import evaluator  # noqa: F401  (puts the repository root on sys.path)
import relational_analysis as ra  # noqa: E402
import relational_schema as rs  # noqa: E402
from evaluator.common import RUBRIC
from evaluator.criteria import C, apply_manual, heur


def mixed_naming_convention(names):
    """snake_case and camelCase fields in the same database: inconsistent naming convention."""
    names = {n for n in names if n not in ("_id", "__v")}
    snake = sorted(n for n in names if "_" in n.strip("_") and n == n.lower())
    camel = sorted(n for n in names if re.search(r"[a-z][A-Z]", n))
    return [f"mixed naming convention (snake_case: {', '.join(snake[:3])}; camelCase: {', '.join(camel[:3])})"] if snake and camel else []


def eval_data_model(m, manual, opts):
    """C1-C6 over the relational schema. With a live database dump (pg_schema.json, --postgres) C1, C3, C4 and C6 are decided on the
    catalog of the real database; otherwise on the schema extracted statically. C2 and C5 are suggestions (heuristics)."""
    T = RUBRIC["thresholds"]["data_model"]; Rr = RUBRIC["relational"]; D = RUBRIC["points"]["data_model"]["criteria"]
    static = m["schema"]
    pg = m.get("pg") or {}
    live = ra.from_catalog(pg, Rr) if pg.get("tables") else None
    S = live or static
    src = "auto (live database)" if live else "auto"
    er = m.get("er") or {"found": False, "diagram": False}
    ast = m["ast"]
    # C1: primary keys and declared foreign keys
    no_pk = ra.tables_without_pk(S); implicit = ra.implicit_relations(S, Rr)
    c1 = bool(S["tables"]) and not no_pk and not implicit
    # C3: constraints declared in the schema, and appropriate types for money
    cs = ra.constraint_stats(S, Rr)
    c3 = bool(cs["total"]) and cs["pct"] >= T["constraints_min_pct"] and not cs["float_money"]
    # C4: indexes on FK columns and on the fields the code filters by (Sequelize `where` and raw SQL)
    queries = list(ast.get("queryFields", [])) + ra.sql_filters(ast.get("sqlStrings", []), S)
    idx = ra.index_analysis(S, queries, T["unindexed_queries_max_pct"], static.get("model_tables"))
    # C2 (suggestion): no repeating groups, no unjustified denormalized copies, no reads inside loops (N+1)
    docs_text = (m.get("readme") or "") + "\n" + (er.get("text") or "")
    reps = ra.repeating_groups(S); copies = ra.denormalized_copies(S, docs_text, Rr)
    unjustified = [c for c in copies if not c["justified"]]
    loop_reads = [f"{q['file']}:{q['line']} {q['model']}.{q['call']}" for q in ast.get("queryFields", [])
                  if q.get("inLoop") and rs.table_for_model(q["model"], {"tables": S["tables"], "model_tables": static.get("model_tables", {})})]
    c2 = bool(S["tables"]) and not reps and not unjustified and not loop_reads
    # C5 (suggestion): same column name with different types, identical tables, mixed naming convention
    conflicts = ra.type_conflicts(S) + mixed_naming_convention({c for t in S["tables"].values() for c in t["columns"]})
    dups = ra.duplicate_tables(S)
    c5 = bool(S["tables"]) and not conflicts and not dups
    # C6: the declared ER corresponds to the implemented schema
    if not er.get("found"):
        c6, cmp, c6v = False, None, f"ER model not found (looked for {ra.er_searched(Rr)})"
    elif not er.get("diagram"):
        c6, cmp, c6v = False, None, f"{er['file']} has no Mermaid erDiagram with entities"
    else:
        cmp = ra.compare_er(er, S, Rr); c6 = cmp["matches"]
        c6v = "matches" if c6 else {k: v for k, v in cmp.items() if v and k not in ("matches", "mismatches", "type_differences", "optionality_differences")}
    crit = {"C1": C(c1, D["C1"], {"tables": len(S["tables"]), "without_primary_key": no_pk, "implicit_relations": implicit}, source=src),
            "C2": heur(C(None, D["C2"], {"repeating_groups": reps, "denormalized_copies": copies, "reads_in_loops": loop_reads}, suggested=c2), opts),
            "C3": C(c3, D["C3"].format(**T), {"constrained_columns": f"{cs['constrained']}/{cs['total']} = {cs['pct']:.0f}%", "float_money_columns": cs["float_money"],
                                             "natural_keys_without_unique": cs["natural_keys_without_unique"]}, source=src),
            "C4": C(idx["ok"], D["C4"], {k: idx[k] for k in ("fks_without_index", "unindexed_queries", "unindexed_queries_pct", "distinct_queries", "unresolved_queries")}, source=src),
            "C5": heur(C(None, D["C5"], {"conflicts": conflicts, "duplicate_tables": dups}, suggested=c5), opts),
            "C6": C(c6, D["C6"], c6v, source=("auto (live database)" if live and cmp else "auto"))}
    apply_manual("data_model", crit, manual)
    ev = [f"table {n} [{t['source']}]: PK {', '.join(t['primary_key']) or 'none'}; {len(t['columns'])} columns; {len(t['foreign_keys'])} FK; {len(t['indexes'])} index(es)"
          for n, t in list(S["tables"].items())[:6]]
    ev += [f"no primary key: {x}" for x in no_pk[:3]] + [f"implicit relation {x}" for x in implicit[:3]] + [f"FLOAT money {x}" for x in cs["float_money"][:2]]
    ev += [f"FK without index {x}" for x in idx["fks_without_index"][:3]] + [f"unindexed filter {x}" for x in idx["unindexed_queries"][:3]]
    ev += [f"read in loop {x}" for x in loop_reads[:2]] + [f"{x}" for x in conflicts[:3]] + [f"copy {c['copy']} of {c['of']}" + ("" if c["justified"] else " (unjustified)") for c in copies[:2]]
    if isinstance(c6v, dict):
        ev += [f"ER vs schema {k}: {v}" for k, v in list(c6v.items())[:3]]
    ev += [f"not part of the main schema (secondary database): {x['file']} ({x['reason']})" for x in static.get("secondary_sql", [])[:2]]
    met = {"tables": len(S["tables"]), "tables_without_pk": len(no_pk), "implicit_relations": len(implicit), "constrained_columns_pct": round(cs["pct"], 1),
           "fks_without_index": len(idx["fks_without_index"]), "unindexed_queries_pct": idx["unindexed_queries_pct"], "queries_analyzed": idx["distinct_queries"],
           "queries_unresolved": idx["unresolved_queries"], "dynamic_queries": idx["dynamic_queries"], "conflicts": len(conflicts), "duplicate_tables": len(dups),
           "er_found": bool(er.get("found")), "er_mismatches": cmp["mismatches"] if cmp else None, "live_database": bool(live),
           "redundant_indexes": idx["redundant"], "unused_indexes": idx["unused"], "schema_unparsed": static.get("unparsed", [])[:5],
           "secondary_sql_skipped": static.get("secondary_sql", [])[:10]}
    return crit, met, ev, f"{rs.summary(S)}{' (live database)' if live else ''}; {len(no_pk)} without primary key, {len(implicit)} implicit relation(s), " \
        f"{cs['pct']:.0f}% of columns constrained, {len(idx['fks_without_index'])} FK without index; ER " + ("matches." if c6 else ("does not match." if er.get("diagram") else "missing.")), None
