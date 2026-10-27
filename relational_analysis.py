#!/usr/bin/env python3
"""
relational_analysis.py — What the data_model criteria measure over a normalized schema (see relational_schema.py).

  C1  tables_without_pk, implicit_relations
  C2  repeating_groups, denormalized_copies                (suggestion only)
  C3  constraint_stats
  C4  index_analysis, sql_filters
  C5  type_conflicts, duplicate_tables                     (suggestion only)
  C6  parse_er, load_er, compare_er                        (Mermaid erDiagram vs. the schema)

Thresholds and lists come from rubric.json (relational / thresholds.data_model); nothing is hard-coded here.
Python standard library only.
"""
import re
from pathlib import Path

from relational_schema import IDENT, QNAME, fold, ident_name, qname_table, singular, table_for_model, type_family


# ───────────────────────── live catalog (pg_schema.js output) ─────────────────────────
def from_catalog(cat, R):
    """pg_schema.js dumps the real database in (almost) the normalized shape; this adds type families and sources."""
    ignore = {fold(x) for x in R.get("ignore_tables", [])}
    tables = {}
    for name, t in (cat.get("tables") or {}).items():
        if fold(name) in ignore:
            continue
        cols = {c: {**d, "family": type_family(d.get("type"), R), "source": "database"} for c, d in t["columns"].items()}
        tables[name] = {"name": name, "columns": cols, "primary_key": list(t.get("primary_key") or []), "primary_key_source": "database",
                        "foreign_keys": [{**f, "source": "database"} for f in t.get("foreign_keys", [])],
                        "unique": [{**u, "source": "database"} for u in t.get("unique", [])],
                        "checks": [{**c, "source": "database"} for c in t.get("checks", [])],
                        "indexes": [{**i, "source": "database"} for i in t.get("indexes", [])],
                        "source": "database", "file": None, "rows": t.get("rows")}
    return {"tables": tables, "sources": {"database": len(tables)}, "model_tables": {}, "unparsed": [],
            "server_version": cat.get("server_version"), "database": cat.get("database")}


# ───────────────────────── Mermaid erDiagram ─────────────────────────
ER_ATTR = re.compile(r'^\s*([^\s"]+)\s+([^\s"]+)((?:\s+(?:PK|FK|UK)\s*,?)*)\s*(?:"([^"]*)")?\s*$', re.I)
ER_REL = re.compile(r'^\s*("[^"]+"|[^\s"]+)\s+(\|\||\|o|\}\||\}o)(--|\.\.)(\|\||o\||\|\{|o\{)\s+("[^"]+"|[^\s"]+)\s*(?::\s*(.*))?$')
ER_OPEN = re.compile(r'^\s*("[^"]+"|[^\s"{\[]+)\s*(?:\[\s*"?([^\]"]+)"?\s*\])?\s*\{\s*$')


def parse_er(text):
    """Entities (attributes with type and PK/FK/UK markers) and relationships of the Mermaid `erDiagram` blocks in `text`."""
    blocks = re.findall(r"```\s*mermaid\s*\n(.*?)```", text, re.S | re.I)
    blocks = [b for b in blocks if re.search(r"^\s*erDiagram\b", b, re.M)]
    if not blocks and re.search(r"^\s*erDiagram\b", text, re.M):
        blocks = [text[re.search(r"^\s*erDiagram\b", text, re.M).start():]]
    ents, rels = {}, []
    unq = lambda x: x.strip().strip('"')
    for blk in blocks:
        cur = None
        for line in blk.splitlines():
            ln = line.split("%%")[0].rstrip()
            if not ln.strip() or re.match(r"^\s*erDiagram\b", ln):
                continue
            if cur is not None:
                if ln.strip() == "}":
                    cur = None
                    continue
                m = ER_ATTR.match(ln)
                if m:
                    keys = [k.upper() for k in re.findall(r"PK|FK|UK", m.group(3) or "", re.I)]
                    ents[cur]["attributes"].append({"type": m.group(1), "name": m.group(2), "keys": keys, "comment": m.group(4)})
                continue
            m = ER_OPEN.match(ln)
            if m:
                cur = unq(m.group(1))
                ents.setdefault(cur, {"name": cur, "alias": None, "attributes": []})
                if m.group(2):
                    ents[cur]["alias"] = m.group(2).strip()
                continue
            m = ER_REL.match(ln)
            if m:
                a, b = unq(m.group(1)), unq(m.group(5))
                for e in (a, b):
                    ents.setdefault(e, {"name": e, "alias": None, "attributes": []})
                rels.append({"left": a, "right": b, "left_card": m.group(2), "right_card": m.group(4), "identifying": m.group(3) == "--",
                             "label": unq(m.group(6) or "")})
    return {"entities": ents, "relationships": rels}


def load_er(app, R):
    """Reads docs/entity-relationship-model.md (path in rubric.json; matched case-insensitively) and parses its erDiagram."""
    app = Path(app)
    want = R["er_model_path"].lower()
    docs = app / Path(want).parent
    found = None
    for cand in [app / R["er_model_path"]] + (list(docs.iterdir()) if docs.is_dir() else []):
        if cand.is_file() and cand.relative_to(app).as_posix().lower() == want:
            found = cand
            break
    if not found:
        return {"file": None, "found": False, "diagram": False, "entities": {}, "relationships": [], "text": ""}
    text = found.read_text(encoding="utf-8", errors="replace")
    parsed = parse_er(text)
    return {"file": found.relative_to(app).as_posix(), "found": True, "diagram": bool(parsed["entities"]), **parsed, "text": text}


def norm_entity(name):
    return fold(singular(str(name)))


def card_flags(tok):
    """(many, optional) of a Mermaid cardinality token: `||` one, `|o`/`o|` zero or one, `}|`/`|{` one or more, `}o`/`o{` zero or more."""
    return ("{" in tok or "}" in tok), ("o" in tok)


def compare_er(er, schema, R):
    """Compares the declared ER (parse_er output) with the schema: entities, attributes, primary and foreign keys and relationships.
    Type differences and optionality (zero vs one) are reported but do not count as mismatches."""
    T = schema["tables"]
    tn = {norm_entity(n): n for n in T}
    en = {}
    for name, e in er["entities"].items():
        en[norm_entity(name)] = e
        if e.get("alias"):
            en.setdefault(norm_entity(e["alias"]), e)
    out = {"entities_missing_in_er": sorted(n for k, n in tn.items() if k not in en),
           "entities_not_in_schema": sorted(e["name"] for e in er["entities"].values() if norm_entity(e["name"]) not in tn
                                            and not (e.get("alias") and norm_entity(e["alias"]) in tn)),
           "attributes_missing_in_er": {}, "attributes_not_in_schema": {}, "pk_mismatch": {}, "fk_mismatch": {},
           "relationships_missing_in_er": [], "relationships_not_in_schema": [], "cardinality_mismatch": [],
           "type_differences": [], "optionality_differences": []}
    for k, tname in tn.items():
        e = en.get(k)
        if not e:
            continue
        t = T[tname]
        scols = {fold(c): c for c in t["columns"]}
        eattrs = {fold(a["name"]): a for a in e["attributes"]}
        miss = sorted(c for f, c in scols.items() if f not in eattrs)
        extra = sorted(a["name"] for f, a in eattrs.items() if f not in scols)
        if miss:
            out["attributes_missing_in_er"][tname] = miss
        if extra:
            out["attributes_not_in_schema"][tname] = extra
        spk = {fold(c) for c in t["primary_key"]}
        epk = {f for f, a in eattrs.items() if "PK" in a["keys"]}
        if spk != epk:
            out["pk_mismatch"][tname] = {"schema": sorted(t["primary_key"]), "er": sorted(eattrs[f]["name"] for f in epk)}
        sfk = {fold(c) for fk in t["foreign_keys"] for c in fk["columns"]}
        efk = {f for f, a in eattrs.items() if "FK" in a["keys"]}
        if sfk != efk:
            out["fk_mismatch"][tname] = {"schema": sorted(c for fk in t["foreign_keys"] for c in fk["columns"]),
                                         "er": sorted(eattrs[f]["name"] for f in efk)}
        for f, a in eattrs.items():
            c = t["columns"].get(scols.get(f))
            fam = type_family(a["type"], R)
            if c and fam and c.get("family") and fam != c["family"]:
                out["type_differences"].append(f"{tname}.{c['name']}: ER {a['type']} vs schema {c['type']}")
    # relationships: entity pairs compared without direction; then the many/one side of the line that matches each foreign key
    er_pairs = {}
    for r in er["relationships"]:
        er_pairs.setdefault(frozenset((norm_entity(r["left"]), norm_entity(r["right"]))), []).append(r)
    schema_pairs = {}
    for tname, t in T.items():
        for fk in t["foreign_keys"]:
            parent = next((n for n in T if fold(n) == fold(fk["ref_table"])), fk["ref_table"])
            schema_pairs.setdefault(frozenset((norm_entity(tname), norm_entity(parent))), []).append((tname, parent, fk))
    for key, fks in schema_pairs.items():
        child, parent, fk = fks[0]
        label = f"{child} → {parent}"
        if key not in er_pairs:
            out["relationships_missing_in_er"].append(label)
            continue
        t = T[child]
        fkset = {fold(c) for c in fk["columns"]}
        one_to_one = fkset in [{fold(c) for c in u["columns"]} for u in t["unique"]] + [{fold(c) for c in t["primary_key"]}]
        nullable = any(t["columns"].get(c, {}).get("nullable") for c in fk["columns"])
        ok_shape = False
        for r in er_pairs[key]:
            if norm_entity(child) == norm_entity(parent):  # self reference: any line with a many side counts
                ok_shape = ok_shape or any(card_flags(x)[0] for x in (r["left_card"], r["right_card"]))
                continue
            sides = {norm_entity(r["left"]): card_flags(r["left_card"]), norm_entity(r["right"]): card_flags(r["right_card"])}
            cm, _ = sides[norm_entity(child)]
            pm, po = sides[norm_entity(parent)]
            if not pm and (cm != one_to_one):
                ok_shape = True
                if po != nullable:
                    out["optionality_differences"].append(
                        f"{label}: parent side is {'optional' if po else 'mandatory'} in the ER but the foreign key is {'nullable' if nullable else 'NOT NULL'}")
        if not ok_shape:
            out["cardinality_mismatch"].append(f"{label}: the ER does not show {'one-to-one' if one_to_one else 'many-to-one'} with {parent} on the 'one' side")
    for key, rels in er_pairs.items():
        if key not in schema_pairs:
            out["relationships_not_in_schema"].append(f"{rels[0]['left']} — {rels[0]['right']}")
    out["relationships_missing_in_er"].sort()
    out["relationships_not_in_schema"].sort()
    counted = ("entities_missing_in_er", "entities_not_in_schema", "attributes_missing_in_er", "attributes_not_in_schema", "pk_mismatch", "fk_mismatch",
               "relationships_missing_in_er", "relationships_not_in_schema", "cardinality_mismatch")
    out["mismatches"] = sum(len(out[k]) for k in counted)
    out["matches"] = out["mismatches"] == 0
    return out


# ───────────────────────── C1 – C5 ─────────────────────────
def tables_without_pk(schema):
    return sorted(n for n, t in schema["tables"].items() if not t["primary_key"])


def implicit_relations(schema, R):
    """Columns named like a reference (`*_id`, `*Id`) that are neither a foreign key nor the table's own single-column primary key."""
    pats = [re.compile(p) for p in R["implicit_fk_patterns"]]
    out = []
    for n, t in schema["tables"].items():
        fkcols = {c for fk in t["foreign_keys"] for c in fk["columns"]}
        own = t["primary_key"][0] if len(t["primary_key"]) == 1 else None
        for c in t["columns"]:
            if c not in fkcols and c != own and any(p.search(c) for p in pats):
                out.append(f"{n}.{c}")
    return sorted(out)


def unique_sets(t):
    """Column lists that are unique: primary key, unique constraints and unique indexes without a predicate."""
    sets = [t["primary_key"]] if t["primary_key"] else []
    sets += [u["columns"] for u in t["unique"]]
    sets += [i["columns"] for i in t["indexes"] if i.get("unique") and not i.get("predicate")]
    return sets


def constraint_stats(schema, R):
    """Share of the non-primary-key columns that declare some constraint (NOT NULL, UNIQUE, CHECK or FOREIGN KEY), and type problems."""
    total = constrained = 0
    money_re = re.compile(R["money_name_pattern"], re.I)
    float_money, natural_keys = [], []
    nat = {x.lower() for x in R["natural_key_names"]}
    for n, t in schema["tables"].items():
        uniq = {c for s in unique_sets(t) if len(s) == 1 for c in s}
        checked = {c for ck in t["checks"] for c in ck["columns"]}
        fks = {c for fk in t["foreign_keys"] for c in fk["columns"]}
        for name, c in t["columns"].items():
            if name in t["primary_key"]:
                continue
            total += 1
            if (not c["nullable"]) or name in uniq or name in checked or name in fks:
                constrained += 1
            if c.get("family") == "float" and money_re.search(name):
                float_money.append(f"{n}.{name} ({c['type']})")
            if name.lower() in nat and name not in uniq:
                natural_keys.append(f"{n}.{name}")
    return {"total": total, "constrained": constrained, "pct": (100.0 * constrained / total) if total else 0.0,
            "float_money": sorted(float_money), "natural_keys_without_unique": sorted(natural_keys)}


def leading_columns(t):
    """Column lists an index can serve, in index order: primary key, unique constraints and indexes."""
    lists = [t["primary_key"]] if t["primary_key"] else []
    lists += [u["columns"] for u in t["unique"]]
    lists += [i["columns"] for i in t["indexes"]]
    return [l for l in lists if l]


def resolve_column(t, field):
    """Attribute name used in a query (`userId`) -> the column of the table (`user_id`); None if the table has no such column."""
    if field in t["columns"]:
        return field
    f = fold(field)
    return next((c for c in t["columns"] if fold(c) == f), None)


SQL_STOP = r"\b(?:GROUP\s+BY|ORDER\s+BY|LIMIT|OFFSET|RETURNING|HAVING|UNION|FOR\s+UPDATE|WINDOW)\b"
SQL_NOT_ALIAS = {"where", "join", "on", "set", "left", "right", "inner", "outer", "cross", "full", "using", "group", "order", "limit", "values", "natural", "returning"}
SQL_OPS = r"(?:=|<>|!=|<=|>=|<|>|\bnot\s+in\b|\bin\b|\blike\b|\bilike\b|\bis\b|\bbetween\b)"


def sql_filters(sql_strings, schema):
    """Table and WHERE columns of the raw SELECT/UPDATE/DELETE strings in the code (best effort): [{file, line, table, fields}]."""
    T = schema["tables"]
    by_fold = {fold(n): n for n in T}
    out = []
    for s in sql_strings:
        text = re.sub(r"\s+", " ", s["text"])
        if re.match(r"\s*(create|alter|drop|insert)\b", text, re.I):
            continue
        aliases = {}
        for m in re.finditer(rf"\b(?:FROM|JOIN|UPDATE|DELETE\s+FROM)\s+({QNAME})(?:\s+(?:AS\s+)?({IDENT}))?", text, re.I):
            tn = by_fold.get(fold(qname_table(m.group(1))))
            if not tn:
                continue
            aliases[tn.lower()] = tn
            if m.group(2) and ident_name(m.group(2)).lower() not in SQL_NOT_ALIAS:
                aliases[ident_name(m.group(2)).lower()] = tn
        mw = re.search(r"\bWHERE\b(.*?)(?:" + SQL_STOP + r"|$)", text, re.I)
        if not aliases or not mw:
            continue
        per = {}
        for m in re.finditer(rf"(?:({IDENT})\.)?({IDENT})\s*{SQL_OPS}", mw.group(1), re.I):
            q, col = (ident_name(m.group(1)).lower() if m.group(1) else None), ident_name(m.group(2))
            tn = aliases.get(q) if q else None
            if not tn and not q:
                cands = {t for t in set(aliases.values()) if resolve_column(T[t], col)}
                tn = next(iter(cands)) if len(cands) == 1 else None
            c = resolve_column(T[tn], col) if tn else None
            if c:
                per.setdefault(tn, set()).add(c)
        out += [{"file": s["file"], "line": s["line"], "table": tn, "fields": sorted(cols), "call": "sql"} for tn, cols in per.items()]
    return out


def index_analysis(schema, queries, max_unindexed_pct, model_tables=None):
    """FK columns without an index, and query filters (Sequelize `where` and raw SQL) that no index can serve.
    `queries`: ast queryFields ({model, fields}) and/or sql_filters entries ({table, fields}); `model_tables` maps models to tables."""
    T = schema["tables"]
    fk_unindexed = []
    for n, t in T.items():
        lead = leading_columns(t)
        for fk in t["foreign_keys"]:
            need = {fold(c) for c in fk["columns"]}
            if not any({fold(c) for c in l[:len(fk["columns"])]} == need for l in lead):
                fk_unindexed.append(f"{n}({', '.join(fk['columns'])})")
    shapes, unindexed, dynamic, unresolved = set(), [], 0, 0
    for q in queries:
        tn = q.get("table") or table_for_model(q.get("model", ""), {"tables": T, "model_tables": model_tables or {}})
        dynamic += bool(q.get("dynamic"))
        if not tn or tn not in T:
            unresolved += 1
            continue
        t = T[tn]
        cols = sorted({resolve_column(t, f) for f in q.get("fields", []) if resolve_column(t, f)})
        if not cols:
            continue
        if len(t["primary_key"]) == 1 and {fold(c) for c in cols} == {fold(t["primary_key"][0])}:
            continue  # filters by the primary key only: resolved by its own index
        if (tn, tuple(cols)) in shapes:
            continue
        shapes.add((tn, tuple(cols)))
        firsts = {fold(l[0]) for l in leading_columns(t)}
        if not {fold(c) for c in cols} & firsts:
            unindexed.append(f"{tn}.where({', '.join(cols)})" + (f" in {q['file']}:{q['line']}" if q.get("file") else ""))
    pct_un = 100.0 * len(unindexed) / len(shapes) if shapes else 0.0
    redundant = []
    for n, t in T.items():
        ixs = [(i["name"], i["columns"], i.get("unique")) for i in t["indexes"]]
        redundant += [f"{n}: {a} is a prefix of {b}" for a, ka, ua in ixs for b, kb, ub in ixs if a != b and not ua and len(ka) < len(kb) and kb[:len(ka)] == ka]
    unused = [f"{n}.{i['name']}" for n, t in T.items() for i in t["indexes"] if i.get("scans") == 0 and not i.get("unique")]
    return {"fks_without_index": sorted(fk_unindexed), "unindexed_queries": unindexed, "distinct_queries": len(shapes), "unindexed_queries_pct": round(pct_un, 1),
            "unresolved_queries": unresolved, "dynamic_queries": dynamic, "redundant": redundant, "unused": unused,
            "ok": not fk_unindexed and pct_un <= max_unindexed_pct}


def repeating_groups(schema):
    out = []
    for n, t in schema["tables"].items():
        stems = {}
        for c in t["columns"]:
            m = re.match(r"^(.*?)_?(\d+)$", c)
            if m and m.group(1):
                stems.setdefault(m.group(1), []).append(c)
        out += [f"{n}: {', '.join(v)}" for v in stems.values() if len(v) >= 2]
    return out


def denormalized_copies(schema, text, R):
    """Columns that copy a column of the referenced table (`product_name` next to `product_id`) and whether the README or the ER
    document justifies them (a word from rubric.json within 200 characters of the column name)."""
    words = [w.lower() for w in R["denormalization_words"]]
    skip = {fold(x) for x in R["boilerplate_columns"]}
    low = text.lower()
    out = []
    for n, t in schema["tables"].items():
        for fk in t["foreign_keys"]:
            p = schema["tables"].get(fk["ref_table"])
            if not p:
                continue
            for pc in p["columns"]:
                if fold(pc) in skip or pc in p["primary_key"]:
                    continue
                col = next((c for c in t["columns"] if fold(c) == fold(f"{singular(fk['ref_table'])}_{pc}")), None)
                if col:
                    near = [low[max(0, m.start() - 200):m.end() + 200] for m in re.finditer(re.escape(col.lower()), low)]
                    out.append({"copy": f"{n}.{col}", "of": f"{fk['ref_table']}.{pc}", "justified": any(w in x for x in near for w in words)})
    return out


def type_conflicts(schema):
    """Same column name (ignoring case and `_`) with different type families in different tables."""
    by = {}
    for n, t in schema["tables"].items():
        for c in t["columns"].values():
            fam = c.get("family") or re.sub(r"\(.*", "", c["type"])
            by.setdefault(fold(c["name"]), {}).setdefault(fam, []).append(f"{n}.{c['name']}")
    return [f"{k}: " + " vs ".join(f"{fam} ({', '.join(v[:3])})" for fam, v in d.items()) for k, d in sorted(by.items()) if len(d) > 1]


def duplicate_tables(schema):
    sig = {}
    for n, t in schema["tables"].items():
        if len(t["columns"]) >= 3:
            sig.setdefault(tuple(sorted((fold(c["name"]), c.get("family")) for c in t["columns"].values())), []).append(n)
    return [" = ".join(v) for v in sig.values() if len(v) > 1]
