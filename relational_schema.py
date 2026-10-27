#!/usr/bin/env python3
"""
relational_schema.py — Static extraction of a relational (PostgreSQL) schema from a generated application.

Sources, in order of preference (rubric.json -> relational.source_preference):
  1. sql                  *.sql files (migrations, schema.sql, Prisma migration.sql…): CREATE/ALTER TABLE, CREATE INDEX
  2. sequelize_migration  queryInterface.createTable / addColumn / addConstraint / addIndex (found by ast_metrics.js)
  3. sequelize_model      sequelize.define / Model.init and belongsTo / hasMany / hasOne / belongsToMany

A table is decided entirely by the first source that defines it; lower sources only contribute tables the higher ones do
not mention. Every element of the result carries the `source` that decided it.

Normalized structure (also what pg_schema.js reads from a live database, with source "database"):
  {"tables": {name: {"columns": {col: {"name", "type", "family", "nullable", "default", "source"}},
                     "primary_key": [cols], "primary_key_source": src,
                     "foreign_keys": [{"columns", "ref_table", "ref_columns", "name", "on_delete", "source"}],
                     "unique": [{"columns", "name", "source"}], "checks": [{"expr", "columns", "name", "source"}],
                     "indexes": [{"name", "columns", "unique", "method", "source"}], "source", "file"}},
   "sources": {src: n_tables}, "model_tables": {model: table}, "unparsed": [...]}

Python standard library only. The SQL parser is a pragmatic subset (see docs/limitations.md): it is not a PostgreSQL parser.
"""
import re

# ───────────────────────── identifiers and text scanning ─────────────────────────
IDENT = r'(?:"(?:[^"]|"")+"|[A-Za-z_][\w$]*)'
QNAME = rf"{IDENT}(?:\s*\.\s*{IDENT})*"


def ident_name(tok):
    """Unquoted identifiers fold to lower case (PostgreSQL); quoted ones keep their case."""
    tok = tok.strip()
    return tok[1:-1].replace('""', '"') if tok.startswith('"') else tok.lower()


def qname_table(tok):
    """`public.users` -> `users` (the schema is ignored: the evaluated apps use one)."""
    parts = re.findall(IDENT, tok)
    return ident_name(parts[-1]) if parts else tok.strip()


def fold(name):
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def snake(name):
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(name)).lower()


def singular(word):
    w = str(word)
    if re.search(r"ies$", w, re.I) and len(w) > 3:
        return w[:-3] + "y"
    if re.search(r"(ses|xes|zes|ches|shes)$", w, re.I):
        return w[:-2]
    if w.lower().endswith("s") and not w.lower().endswith("ss"):
        return w[:-1]
    return w


def plural(word):
    """Approximation of Sequelize's inflection-based pluralization (regular English plurals only)."""
    w = str(word)
    if re.search(r"[^aeiou]y$", w, re.I):
        return w[:-1] + "ies"
    if re.search(r"(s|x|z|ch|sh)$", w, re.I):
        return w + "es"
    return w + "s"


def clean_and_split(sql):
    """Removes comments, blanks dollar-quoted bodies and splits into statements on ';' (outside quotes and parentheses)."""
    out, buf, i, n, depth = [], [], 0, len(sql), 0
    while i < n:
        c = sql[i]
        if c == "-" and sql.startswith("--", i):
            j = sql.find("\n", i)
            i = n if j < 0 else j
            continue
        if c == "/" and sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            i = n if j < 0 else j + 2
            buf.append(" ")
            continue
        if c in "'\"":
            j = i + 1
            while j < n:
                if sql[j] == c:
                    if j + 1 < n and sql[j + 1] == c:
                        j += 2
                        continue
                    break
                j += 1
            buf.append(sql[i:j + 1])
            i = j + 1
            continue
        if c == "$":
            m = re.match(r"\$[A-Za-z_]*\$", sql[i:])
            if m:
                tag = m.group(0)
                j = sql.find(tag, i + len(tag))
                buf.append("''")
                i = n if j < 0 else j + len(tag)
                continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif c == ";" and depth <= 0:
            stmt = "".join(buf).strip()
            if stmt:
                out.append(stmt)
            buf, depth = [], 0
            i += 1
            continue
        buf.append(c)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        out.append(tail)
    return out


def mask(s):
    """Replaces what is inside parentheses and quotes by `_`, so keywords can be searched at the top level only."""
    out, depth, q = [], 0, None
    for c in s:
        if q:
            out.append("_")
            if c == q:
                q = None
        elif c in "'\"":
            q = c
            out.append("_")
        elif c == "(":
            depth += 1
            out.append("(" if depth == 1 else "_")
        elif c == ")":
            out.append(")" if depth == 1 else "_")
            depth = max(0, depth - 1)
        else:
            out.append("_" if depth else c)
    return "".join(out)


def split_top(s, sep=","):
    parts, cur, depth, q = [], [], 0, None
    for c in s:
        if q:
            cur.append(c)
            if c == q:
                q = None
            continue
        if c in "'\"":
            q = c
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif c == sep and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
            continue
        cur.append(c)
    if "".join(cur).strip():
        parts.append("".join(cur).strip())
    return parts


def match_paren(s, start):
    """Index of the parenthesis that closes s[start] == '('; -1 if unbalanced."""
    depth, q = 0, None
    for i in range(start, len(s)):
        c = s[i]
        if q:
            if c == q:
                q = None
        elif c in "'\"":
            q = c
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i
    return -1


def col_list(txt):
    """`(a, "B", lower(c))` contents -> ['a', 'B', 'lower(c)']; plain identifiers lose quotes/ordering words."""
    cols = []
    for part in split_top(txt):
        m = re.match(rf"^\s*({IDENT})\s*(?:(?:ASC|DESC)\b|NULLS\s+(?:FIRST|LAST)\b|\w+_ops\b|\s)*$", part, re.I)
        cols.append(ident_name(m.group(1)) if m else re.sub(r"\s+", " ", part.strip()))
    return cols


# ───────────────────────── types ─────────────────────────
def type_family(raw, R):
    """Family of a type (integer, numeric, float, string, boolean, date, timestamp, uuid, json, binary, enum, array) or None."""
    t = re.sub(r"\(.*?\)", "", str(raw or "").lower()).strip()
    known = sum(R["type_families"].values(), [])
    if t.endswith("[]") or (t.startswith("_") and t[1:] in known):  # `_int4` is how pg_catalog names int4[]
        return "array"
    t = re.sub(r"\s+", " ", t)
    for fam, names in R["type_families"].items():
        if t in names:
            return fam
    return None


def sequelize_type(expr, R):
    """`Sequelize.STRING(100)` -> `varchar(100)`; `DataTypes.DECIMAL(10, 2)` -> `numeric(10,2)`; unknown types keep their name."""
    if isinstance(expr, dict):
        expr = expr.get("$expr", "")
    txt = str(expr or "").strip()
    m = re.match(r"^(?:[\w$]+\.)*([A-Za-z0-9_]+)(?:\((.*)\))?(?:\.\w+)*$", txt, re.S)
    if not m:
        return txt.lower()
    name, args = m.group(1).upper(), (m.group(2) or "").strip()
    base = R["sequelize_types"].get(name)
    if base is None:
        return name.lower()
    if name == "ARRAY":
        inner = sequelize_type(args, R) if args else "unknown"
        return inner + "[]"
    if name == "ENUM":
        return "enum"
    if args and re.fullmatch(r"[\d\s,]+", args):
        compact = re.sub(r"\s+", "", args)
        return base.split("(")[0] + "(" + compact + ")"
    return base


# ───────────────────────── schema builder ─────────────────────────
class Builder:
    """Accumulates tables of ONE source; `Builder.schema` is the normalized structure."""

    def __init__(self, source):
        self.source = source
        self.tables = {}
        self.unparsed = []

    def find(self, name):
        if name in self.tables:
            return name
        f = fold(name)
        return next((t for t in self.tables if fold(t) == f), None)

    def table(self, name, file=None, create=False):
        key = self.find(name)
        if key is None:
            if not create:
                return None
            key = name
            self.tables[key] = {"name": key, "columns": {}, "primary_key": [], "primary_key_source": None, "foreign_keys": [],
                                "unique": [], "checks": [], "indexes": [], "source": self.source, "file": file}
        return self.tables[key]

    def drop_table(self, name):
        key = self.find(name)
        if key:
            del self.tables[key]

    def column(self, t, name, typ, R, nullable=True, default=None):
        t["columns"][name] = {"name": name, "type": typ, "family": type_family(typ, R), "nullable": nullable, "default": default, "source": self.source}
        return t["columns"][name]

    def primary_key(self, t, cols):
        t["primary_key"] = list(cols)
        t["primary_key_source"] = self.source
        for c in cols:
            if c in t["columns"]:
                t["columns"][c]["nullable"] = False

    def foreign_key(self, t, cols, ref_table, ref_cols, name=None, on_delete=None):
        if any(fk["columns"] == list(cols) and fold(fk["ref_table"]) == fold(ref_table) for fk in t["foreign_keys"]):
            return
        t["foreign_keys"].append({"columns": list(cols), "ref_table": ref_table, "ref_columns": list(ref_cols), "name": name,
                                  "on_delete": on_delete, "source": self.source})

    def unique(self, t, cols, name=None):
        if not any(u["columns"] == list(cols) for u in t["unique"]):
            t["unique"].append({"columns": list(cols), "name": name, "source": self.source})

    def check(self, t, expr, name=None, cols=None):
        if cols is None:
            toks = {ident_name(x) for x in re.findall(IDENT, expr)}
            cols = [c for c in t["columns"] if c in toks]
        t["checks"].append({"expr": expr.strip(), "columns": cols, "name": name, "source": self.source})

    def index(self, t, name, cols, unique=False, method=None, predicate=None):
        t["indexes"].append({"name": name, "columns": list(cols), "unique": bool(unique), "method": method, "predicate": predicate, "source": self.source})


# ───────────────────────── 1. SQL ─────────────────────────
COL_KW = re.compile(r"\b(NOT\s+NULL|NULL|DEFAULT|PRIMARY\s+KEY|UNIQUE|REFERENCES|CHECK|CONSTRAINT|GENERATED|COLLATE|COMPRESSION|STORAGE|AS)\b", re.I)
ACTIONS = r"CASCADE|SET\s+NULL|SET\s+DEFAULT|RESTRICT|NO\s+ACTION"
SERIAL = {"serial": "integer", "serial4": "integer", "bigserial": "bigint", "serial8": "bigint", "smallserial": "smallint", "serial2": "smallint"}


def apply_references(seg):
    m = re.match(rf"REFERENCES\s+({QNAME})\s*(?:\(([^)]*)\))?", seg, re.I)
    if not m:
        return None
    od = re.search(rf"ON\s+DELETE\s+({ACTIONS})", seg, re.I)
    return qname_table(m.group(1)), (col_list(m.group(2)) if m.group(2) else []), (re.sub(r"\s+", " ", od.group(1).upper()) if od else None)


def parse_column(b, t, item, R):
    m = re.match(rf"\s*({IDENT})\s+(.*)$", item, re.S)
    if not m:
        b.unparsed.append(f"column not understood in {t['name']}: {item[:60]}")
        return
    name, rest = ident_name(m.group(1)), m.group(2)
    masked = mask(rest)
    km = COL_KW.search(masked)
    type_txt = re.sub(r"\s*,\s*", ",", re.sub(r"\s+", " ", (rest[:km.start()] if km else rest).strip()))
    mods, mmask = (rest[km.start():], masked[km.start():]) if km else ("", "")
    base = re.sub(r"\(.*?\)", "", type_txt.lower()).strip()
    typ = type_txt.lower()
    nullable, default = True, None
    if base in SERIAL:
        nullable, default = False, "nextval(serial)"
    starts = [x.start() for x in COL_KW.finditer(mmask)]
    segs = [mods[a:(starts[i + 1] if i + 1 < len(starts) else len(mods))].strip() for i, a in enumerate(starts)]
    cname, pk, uniq, fk, chk = None, False, False, None, []
    i = 0
    while i < len(segs):
        seg = segs[i]
        up = seg.upper()
        if up.startswith("CONSTRAINT"):
            mm = re.match(rf"CONSTRAINT\s+({IDENT})", seg, re.I)
            cname = ident_name(mm.group(1)) if mm else None
        elif up.startswith("NOT NULL") or re.match(r"NOT\s+NULL", up):
            nullable = False
        elif up == "NULL":
            nullable = True
        elif up.startswith("DEFAULT"):
            default = seg[7:].strip()
            if i + 1 < len(segs) and segs[i + 1].upper() == "NULL":  # DEFAULT NULL is a default, not a nullability marker
                default = "NULL"
                i += 1
        elif re.match(r"PRIMARY\s+KEY", up):
            pk = True
        elif up.startswith("UNIQUE"):
            uniq = True
        elif up.startswith("REFERENCES"):
            fk = apply_references(seg)
        elif up.startswith("CHECK"):
            p = seg.find("(")
            e = match_paren(seg, p) if p >= 0 else -1
            if e > p:
                chk.append(seg[p + 1:e])
        elif up.startswith("GENERATED") or up.startswith("AS"):
            default = "identity" if "IDENTITY" in up or any("IDENTITY" in x.upper() for x in segs[i:i + 2]) else "generated"
            if "IDENTITY" in " ".join(segs[i:i + 2]).upper():
                nullable = False
        i += 1
    if base in SERIAL:
        typ = SERIAL[base]
    c = b.column(t, name, typ, R, nullable, default)
    if pk:
        b.primary_key(t, [name])
    if uniq:
        b.unique(t, [name], cname)
    if fk:
        b.foreign_key(t, [name], fk[0], fk[1], cname, fk[2])
    for e in chk:
        b.check(t, e, cname, [name])
    return c


def parse_table_constraint(b, t, item):
    """[CONSTRAINT name] PRIMARY KEY (..) | UNIQUE (..) | FOREIGN KEY (..) REFERENCES t (..) | CHECK (..) -> True if recognized."""
    m = re.match(rf"\s*(?:CONSTRAINT\s+({IDENT})\s+)?(PRIMARY\s+KEY|UNIQUE|FOREIGN\s+KEY|CHECK|EXCLUDE)\b\s*(.*)$", item, re.I | re.S)
    if not m:
        return False
    name = ident_name(m.group(1)) if m.group(1) else None
    kind, rest = re.sub(r"\s+", " ", m.group(2).upper()), m.group(3)
    if kind == "EXCLUDE":
        return True
    p = rest.find("(")
    e = match_paren(rest, p) if p >= 0 else -1
    if e < 0:
        b.unparsed.append(f"constraint not understood in {t['name']}: {item[:60]}")
        return True
    inner, after = rest[p + 1:e], rest[e + 1:]
    if kind == "CHECK":
        b.check(t, inner, name)
    elif kind == "PRIMARY KEY":
        b.primary_key(t, col_list(inner))
    elif kind == "UNIQUE":
        b.unique(t, col_list(inner), name)
    else:
        ref = apply_references(after.strip())
        if ref:
            b.foreign_key(t, col_list(inner), ref[0], ref[1], name, ref[2])
        else:
            b.unparsed.append(f"foreign key without REFERENCES in {t['name']}")
    return True


def apply_sql(b, text, file, R):
    for stmt in clean_and_split(text):
        s = re.sub(r"\s+", " ", stmt).strip()
        up = s.upper()
        m = re.match(rf"CREATE (?:(?:GLOBAL |LOCAL )?(?:TEMP|TEMPORARY) |UNLOGGED )?TABLE (?:IF NOT EXISTS )?({QNAME})\s*\(", s, re.I)
        if m:
            p = m.end() - 1
            e = match_paren(s, p)
            if e < 0:
                b.unparsed.append(f"CREATE TABLE not closed in {file}")
                continue
            t = b.table(qname_table(m.group(1)), file, create=True)
            t.update({"columns": {}, "primary_key": [], "foreign_keys": [], "unique": [], "checks": [], "indexes": []})
            items = split_top(s[p + 1:e])
            consts = [x for x in items if re.match(r"\s*(?:CONSTRAINT\b|PRIMARY\s+KEY\b|UNIQUE\s*\(|FOREIGN\s+KEY\b|CHECK\s*\(|EXCLUDE\b)", x, re.I)]
            for item in items:
                if item in consts or re.match(r"\s*(LIKE|INHERITS)\b", item, re.I):
                    continue
                parse_column(b, t, item, R)
            for item in consts:
                parse_table_constraint(b, t, item)
            continue
        if re.match(r"CREATE (?:UNLOGGED )?TABLE ", up):
            b.unparsed.append(f"CREATE TABLE form not understood in {file}: {s[:70]}")
            continue
        m = re.match(rf"ALTER TABLE (?:ONLY )?(?:IF EXISTS )?({QNAME}) (.*)$", s, re.I)
        if m:
            t = b.table(qname_table(m.group(1)))
            if t is None:
                b.unparsed.append(f"ALTER TABLE on a table not created before: {qname_table(m.group(1))} ({file})")
                continue
            for act in split_top(m.group(2)):
                a = act.strip()
                ma = re.match(r"ADD (?:COLUMN )?(?:IF NOT EXISTS )?(.*)$", a, re.I | re.S)
                if ma and not re.match(r"(CONSTRAINT|PRIMARY|UNIQUE|FOREIGN|CHECK|EXCLUDE)\b", ma.group(1), re.I) and not re.match(r"ADD (CONSTRAINT|PRIMARY|UNIQUE|FOREIGN|CHECK)", a, re.I):
                    parse_column(b, t, ma.group(1), R)
                elif re.match(r"ADD (CONSTRAINT|PRIMARY|UNIQUE|FOREIGN|CHECK|EXCLUDE)\b", a, re.I):
                    parse_table_constraint(b, t, a[4:])
                elif re.match(rf"DROP COLUMN (?:IF EXISTS )?({IDENT})", a, re.I):
                    c = ident_name(re.match(rf"DROP COLUMN (?:IF EXISTS )?({IDENT})", a, re.I).group(1))
                    t["columns"].pop(c, None)
                    t["foreign_keys"] = [f for f in t["foreign_keys"] if c not in f["columns"]]
                    t["unique"] = [u for u in t["unique"] if c not in u["columns"]]
                    t["indexes"] = [i for i in t["indexes"] if c not in i["columns"]]
                    if c in t["primary_key"]:
                        t["primary_key"] = []
                elif re.match(rf"DROP CONSTRAINT (?:IF EXISTS )?({IDENT})", a, re.I):
                    n = ident_name(re.match(rf"DROP CONSTRAINT (?:IF EXISTS )?({IDENT})", a, re.I).group(1))
                    for k in ("foreign_keys", "unique", "checks"):
                        t[k] = [x for x in t[k] if x.get("name") != n]
                elif re.match(rf"ALTER (?:COLUMN )?({IDENT}) ", a, re.I):
                    mc = re.match(rf"ALTER (?:COLUMN )?({IDENT}) (.*)$", a, re.I)
                    col, act2 = ident_name(mc.group(1)), mc.group(2)
                    c = t["columns"].get(col)
                    if c is None:
                        b.unparsed.append(f"ALTER COLUMN on unknown column {t['name']}.{col}")
                    elif re.match(r"SET NOT NULL", act2, re.I):
                        c["nullable"] = False
                    elif re.match(r"DROP NOT NULL", act2, re.I):
                        c["nullable"] = True
                    elif re.match(r"SET DEFAULT ", act2, re.I):
                        c["default"] = act2[12:].strip()
                    elif re.match(r"DROP DEFAULT", act2, re.I):
                        c["default"] = None
                    elif re.match(r"(?:SET DATA )?TYPE ", act2, re.I):
                        c["type"] = re.sub(r"\s+USING .*$", "", re.sub(r"^(?:SET DATA )?TYPE ", "", act2, flags=re.I), flags=re.I).strip().lower()
                        c["family"] = type_family(c["type"], R)
                    else:
                        b.unparsed.append(f"ALTER COLUMN not understood: {act2[:50]}")
                else:
                    b.unparsed.append(f"ALTER TABLE action not understood on {t['name']}: {a[:60]}")
            continue
        m = re.match(rf"CREATE (UNIQUE )?INDEX (?:CONCURRENTLY )?(?:IF NOT EXISTS )?({IDENT} )?ON (?:ONLY )?({QNAME})\s*(?:USING (\w+))?\s*\(", s, re.I)
        if m:
            t = b.table(qname_table(m.group(3)))
            if t is None:
                b.unparsed.append(f"CREATE INDEX on a table not created before: {qname_table(m.group(3))} ({file})")
                continue
            p = m.end() - 1
            e = match_paren(s, p)
            cols = col_list(s[p + 1:e])
            tail = s[e + 1:]
            wm = re.search(r"\bWHERE\b(.*)$", tail, re.I | re.S)
            name = ident_name(m.group(2)) if m.group(2) else f"{t['name']}_{'_'.join(cols)}_idx"
            b.index(t, name, cols, bool(m.group(1)), (m.group(4) or "btree").lower(), wm.group(1).strip() if wm else None)
            continue
        m = re.match(rf"DROP TABLE (?:IF EXISTS )?(.+?)(?: CASCADE| RESTRICT)?$", s, re.I)
        if m:
            for x in split_top(m.group(1)):
                b.drop_table(qname_table(x))
            continue
        m = re.match(rf"DROP INDEX (?:CONCURRENTLY )?(?:IF EXISTS )?(.+?)(?: CASCADE| RESTRICT)?$", s, re.I)
        if m:
            names = {qname_table(x) for x in split_top(m.group(1))}
            for t in b.tables.values():
                t["indexes"] = [i for i in t["indexes"] if i["name"] not in names]
        # INSERT, SET, CREATE EXTENSION/TYPE/SEQUENCE/FUNCTION/VIEW/TRIGGER, COMMENT, BEGIN/COMMIT… do not change what is measured


DOWN_MARK = re.compile(r"^\s*--\s*(\+goose\s+down|migrate:down|\+migrate\s+down|\+micrate\s+down|@down)\b", re.I | re.M)


def sql_builder(files, R):
    """`files` = [(relative_path, text)] in application order (sorted by path)."""
    b = Builder("sql")
    for path, text in sorted(files):
        if re.search(r"[._-]down\.sql$", path, re.I):
            continue  # golang-migrate style: the down half undoes the schema
        m = DOWN_MARK.search(text)
        apply_sql(b, text[:m.start()] if m else text, path, R)
    return b


# ───────────────────────── 2. Sequelize migrations ─────────────────────────
def val(x):
    """Unwraps ast_metrics.js' {$expr: text} into text; other values unchanged."""
    return x.get("$expr") if isinstance(x, dict) and "$expr" in x else x


def table_arg(x):
    x = val(x)
    if isinstance(x, dict):
        return val(x.get("tableName"))
    return x if isinstance(x, str) and re.fullmatch(r"[\w$.\- ]+", x) else None


def seq_column(b, t, name, d, R, implicit_pk=False):
    """Applies a Sequelize attribute definition (string/expression shorthand or object) to table `t`."""
    if not isinstance(d, dict) or "$expr" in d:
        d = {"type": d}
    typ = sequelize_type(d.get("type"), R)
    if str(val(d.get("type")) or "").upper().endswith("VIRTUAL"):
        return None
    pk = bool(d.get("primaryKey"))
    c = b.column(t, d.get("field") if isinstance(d.get("field"), str) else name, typ, R,
                 nullable=False if (pk or d.get("allowNull") is False) else True)
    dv = d.get("defaultValue")
    if dv is not None:
        c["default"] = str(val(dv))
    elif d.get("autoIncrement"):
        c["default"] = "autoincrement"
    if pk:
        if c["name"] not in t["primary_key"]:
            t["primary_key"].append(c["name"])
        t["primary_key_source"] = b.source
    if d.get("unique"):
        b.unique(t, [c["name"]], d["unique"] if isinstance(d["unique"], str) else None)
    ref = d.get("references")
    if isinstance(ref, dict):
        target = table_arg(ref.get("model")) or table_arg(ref.get("table"))
        if target:
            k = ref.get("key") or ref.get("field")
            b.foreign_key(t, [c["name"]], target, [k] if k else [], None, d.get("onDelete"))
        else:
            b.unparsed.append(f"reference to a model expression in {t['name']}.{c['name']}: {val(ref.get('model'))}")
    return c


def constraint_cols(fields):
    out = []
    for f in fields if isinstance(fields, list) else []:
        f = val(f)
        out.append(f if isinstance(f, str) else (val(f.get("name") or f.get("attribute")) if isinstance(f, dict) else str(f)))
    return out


def migrations_builder(migs, R):
    b = Builder("sequelize_migration")
    for mg in sorted(migs, key=lambda x: (x["file"], x["line"])):
        a, f = mg["args"], mg["file"]
        tname = table_arg(a[0]) if a else None
        if mg["method"] in ("createTable", "dropTable", "addColumn", "removeColumn", "changeColumn", "addConstraint", "removeConstraint", "addIndex", "removeIndex") and not tname:
            b.unparsed.append(f"{mg['method']} with a table name that is not a literal ({f}:{mg['line']})")
            continue
        m = mg["method"]
        if m == "createTable" and len(a) > 1 and isinstance(a[1], dict):
            t = b.table(tname, f, create=True)
            t.update({"columns": {}, "primary_key": [], "foreign_keys": [], "unique": [], "checks": [], "indexes": []})
            for cname, d in a[1].items():
                if cname != "$spread":
                    seq_column(b, t, cname, d, R)
            if a[1].get("$spread"):
                b.unparsed.append(f"createTable({tname}) spreads columns from {a[1]['$spread']}")
            opts = a[2] if len(a) > 2 and isinstance(a[2], dict) else {}
            for uk in (opts.get("uniqueKeys") or {}).values() if isinstance(opts.get("uniqueKeys"), dict) else []:
                if isinstance(uk, dict):
                    b.unique(t, constraint_cols(uk.get("fields")))
        elif m == "dropTable":
            b.drop_table(tname)
        elif m in ("addColumn", "changeColumn") and len(a) > 2:
            t = b.table(tname)
            if t is None:
                b.unparsed.append(f"{m} on a table not created before: {tname} ({f}:{mg['line']})")
                continue
            if m == "changeColumn" and a[1] in t["columns"]:
                old = t["columns"][a[1]]
                seq_column(b, t, a[1], a[2], R)
                if isinstance(a[2], dict) and "allowNull" not in a[2]:
                    t["columns"][a[1]]["nullable"] = old["nullable"]
            else:
                seq_column(b, t, a[1], a[2], R)
        elif m == "removeColumn" and len(a) > 1:
            t = b.table(tname)
            if t:
                t["columns"].pop(a[1], None)
                t["foreign_keys"] = [x for x in t["foreign_keys"] if a[1] not in x["columns"]]
                t["indexes"] = [x for x in t["indexes"] if a[1] not in x["columns"]]
        elif m == "addConstraint" and len(a) > 1 and isinstance(a[1], dict):
            t = b.table(tname)
            if t is None:
                b.unparsed.append(f"addConstraint on a table not created before: {tname} ({f}:{mg['line']})")
                continue
            c = a[1]
            kind, cols, name = str(val(c.get("type")) or "").lower(), constraint_cols(c.get("fields")), val(c.get("name"))
            if kind == "primary key":
                b.primary_key(t, cols)
            elif kind == "unique":
                b.unique(t, cols, name)
            elif kind == "foreign key":
                r = c.get("references") or {}
                tgt = table_arg(r.get("table")) or table_arg(r.get("model"))
                if tgt:
                    k = r.get("field") or r.get("key")
                    b.foreign_key(t, cols, tgt, [k] if k else [], name, c.get("onDelete"))
            elif kind == "check":
                w = c.get("where")
                wcols = [k for k in w if not k.startswith("[")] if isinstance(w, dict) else cols
                b.check(t, f"check({', '.join(wcols or cols)})", name, wcols or cols)
        elif m == "removeConstraint" and len(a) > 1:
            t = b.table(tname)
            if t:
                for k in ("foreign_keys", "unique", "checks"):
                    t[k] = [x for x in t[k] if x.get("name") != a[1]]
        elif m == "addIndex":
            t = b.table(tname)
            if t is None:
                b.unparsed.append(f"addIndex on a table not created before: {tname} ({f}:{mg['line']})")
                continue
            attrs = a[1] if len(a) > 1 else None
            opts = a[2] if len(a) > 2 and isinstance(a[2], dict) else (attrs if isinstance(attrs, dict) else {})
            fields = attrs if isinstance(attrs, list) else (opts.get("fields") if isinstance(opts, dict) else None)
            cols = constraint_cols(fields)
            if cols:
                name = val(opts.get("name")) if isinstance(opts, dict) and opts.get("name") else f"{t['name']}_{'_'.join(cols)}"
                b.index(t, name, cols, bool(opts.get("unique")) if isinstance(opts, dict) else False,
                        str(val(opts.get("using")) or "btree").lower() if isinstance(opts, dict) else "btree",
                        "partial" if isinstance(opts, dict) and opts.get("where") else None)
        elif m == "removeIndex" and len(a) > 1:
            t = b.table(tname)
            if t:
                t["indexes"] = [i for i in t["indexes"] if i["name"] != a[1] and i["columns"] != constraint_cols(a[1] if isinstance(a[1], list) else [])]
        elif m in ("renameColumn", "renameTable"):
            b.unparsed.append(f"{m} ignored ({f}:{mg['line']}): the resulting names are not tracked")
    return b


def sql_in_migrations(sql_strings, R):
    """Raw DDL executed from JS migrations (queryInterface.sequelize.query('CREATE TABLE …')) goes through the SQL parser."""
    return [(f"{s['file']}:{s['line']}", s["text"]) for s in sql_strings if s.get("migration") and re.match(r"\s*(create|alter|drop)\b", s["text"], re.I)]


# ───────────────────────── 3. Sequelize models ─────────────────────────
def model_table_name(model):
    o = model.get("options") or {}
    if isinstance(o.get("tableName"), str):
        return o["tableName"]
    name = model.get("modelName") or model.get("variable")
    return name if o.get("freezeTableName") else plural(name)


def models_builder(seq, R):
    b = Builder("sequelize_model")
    models = [m for m in seq.get("models", []) if (m.get("modelName") or m.get("variable"))]
    by_ref = {}
    for m in models:
        for key in (m.get("variable"), m.get("modelName")):
            if key:
                by_ref.setdefault(key, m)
    info = {}  # model identity -> {table, underscored, name, attr: {attribute name: column name}}
    for m in models:
        o = m.get("options") or {}
        und = bool(o.get("underscored"))
        t = b.table(model_table_name(m), m["file"], create=True)
        info[id(m)] = {"table": t["name"], "underscored": und, "name": m.get("modelName") or m.get("variable"), "model": m, "attr": {}}
        attrs = m.get("attributes") if isinstance(m.get("attributes"), dict) else {}
        for aname, d in attrs.items():
            if aname == "$spread":
                b.unparsed.append(f"model {info[id(m)]['name']} spreads attributes from {attrs['$spread']}")
                continue
            if und and isinstance(d, dict) and "$expr" not in d and "field" not in d:
                d = {**d, "field": snake(aname)}
            elif und and not (isinstance(d, dict) and "$expr" not in d):
                d = {"type": d, "field": snake(aname)}
            col = seq_column(b, t, aname, d, R)
            if col:
                info[id(m)]["attr"][aname] = col["name"]
        if not t["primary_key"] and o.get("id") is not False and "id" not in t["columns"]:
            b.column(t, "id", "integer", R, nullable=False, default="autoincrement")
            t["primary_key"], t["primary_key_source"] = ["id"], "sequelize_model (implicit id)"
        ts = o.get("timestamps", True)
        if ts is not False:
            for key, default in (("createdAt", "createdAt"), ("updatedAt", "updatedAt")):
                nm = o.get(key, default)
                if nm is not False:
                    nm = snake(nm) if und and nm == default else nm
                    if nm not in t["columns"]:
                        b.column(t, nm, "timestamp with time zone", R, nullable=False)
            if o.get("paranoid"):
                nm = o.get("deletedAt", "deletedAt")
                nm = snake(nm) if und and nm == "deletedAt" else nm
                if nm not in t["columns"]:
                    b.column(t, nm, "timestamp with time zone", R, nullable=True)
        for ix in o.get("indexes") or []:
            if isinstance(ix, dict):
                cols = constraint_cols(ix.get("fields"))
                if cols:
                    b.index(t, val(ix.get("name")) or f"{t['name']}_{'_'.join(cols)}", cols, bool(ix.get("unique")),
                            str(val(ix.get("using")) or "btree").lower(), "partial" if ix.get("where") else None)

    def lookup(ref):
        return by_ref.get(ref)

    def pk_of(t):
        return t["primary_key"][0] if t["primary_key"] else "id"

    def add_fk(table, col, target_table, target_col, nullable, on_delete=None, inf=None):
        if inf:  # the association names an attribute; with `underscored` the column is its snake_case field
            col = inf["attr"].get(col) or (snake(col) if inf["underscored"] and snake(col) in table["columns"] else col)
        c = table["columns"].get(col)
        if c is None:
            tcol = target_table["columns"].get(target_col, {})
            c = b.column(table, col, tcol.get("type", "integer"), R, nullable=nullable)
            c["source"] = "sequelize_model (association)"
        elif nullable is False:
            c["nullable"] = False
        b.foreign_key(table, [col], target_table["name"], [target_col], None, on_delete)

    def fk_name(base, und, pk):
        return snake(base) + "_" + pk if und else f"{base}Id" if pk == "id" else f"{base}{pk[0].upper() + pk[1:]}"

    for a in seq.get("associations", []):
        src, tgt = lookup(a.get("source")), lookup(a.get("target"))
        if not src or not tgt:
            b.unparsed.append(f"association {a.get('source')}.{a['kind']}({a.get('target')}) between models that were not found ({a['file']}:{a['line']})")
            continue
        si, ti = info[id(src)], info[id(tgt)]
        st, tt = b.tables[si["table"]], b.tables[ti["table"]]
        o = a.get("options") or {}
        fkopt = o.get("foreignKey")
        fk_allow = fkopt.get("allowNull") if isinstance(fkopt, dict) else None
        fkn = (fkopt.get("name") or fkopt.get("field")) if isinstance(fkopt, dict) else fkopt
        on_delete = o.get("onDelete") if isinstance(o.get("onDelete"), str) else None
        kind = a["kind"]
        if kind == "belongsTo":
            alias = o.get("as") if isinstance(o.get("as"), str) else singular(ti["name"])
            col = fkn if isinstance(fkn, str) else fk_name(alias, si["underscored"], pk_of(tt))
            add_fk(st, col, tt, pk_of(tt), fk_allow is not False, on_delete, si)
        elif kind in ("hasMany", "hasOne"):
            alias = singular(si["name"])
            col = fkn if isinstance(fkn, str) else fk_name(alias, ti["underscored"], pk_of(st))
            add_fk(tt, col, st, pk_of(st), fk_allow is not False, on_delete, ti)
        elif kind == "belongsToMany":
            thr = val(o.get("through"))
            if isinstance(thr, dict):
                thr = val(thr.get("model"))
            tmodel = lookup(thr) if isinstance(thr, str) else None
            tname = info[id(tmodel)]["table"] if tmodel else (thr if isinstance(thr, str) and re.fullmatch(r"[\w$.\- ]+", thr) else None)
            if not tname:
                b.unparsed.append(f"belongsToMany without a resolvable through table ({a['file']}:{a['line']})")
                continue
            jt = b.table(tname, a["file"], create=True)
            c1 = fkn if isinstance(fkn, str) else fk_name(singular(si["name"]), si["underscored"], pk_of(st))
            c2 = o.get("otherKey") if isinstance(o.get("otherKey"), str) else fk_name(singular(ti["name"]), si["underscored"], pk_of(tt))
            add_fk(jt, c1, st, pk_of(st), False, on_delete)
            add_fk(jt, c2, tt, pk_of(tt), False, on_delete)
            if not tmodel and not jt["primary_key"]:
                jt["primary_key"], jt["primary_key_source"] = [c1, c2], "sequelize_model (belongsToMany)"
                if "createdAt" not in jt["columns"] and "created_at" not in jt["columns"]:
                    for nm in ("createdAt", "updatedAt"):
                        b.column(jt, snake(nm) if si["underscored"] else nm, "timestamp with time zone", R, nullable=False)
    return b, {m.get("modelName") or m.get("variable"): info[id(m)]["table"] for m in models} | {m.get("variable"): info[id(m)]["table"] for m in models if m.get("variable")}


# ───────────────────────── assembling ─────────────────────────
def merge(builders, R):
    """`builders` in order of preference. A table is decided by the first source that defines it."""
    tables, seen = {}, set()
    for b in builders:
        for name, t in b.tables.items():
            if fold(name) in seen:
                continue
            seen.add(fold(name))
            tables[name] = t
    ignore = {fold(x) for x in R.get("ignore_tables", [])}
    tables = {k: v for k, v in tables.items() if fold(k) not in ignore}
    for t in tables.values():  # resolve FK targets to the table names of the final schema
        for fk in t["foreign_keys"]:
            fk["ref_table"] = next((n for n in tables if fold(n) == fold(fk["ref_table"])), fk["ref_table"])
            if not fk["ref_columns"]:
                fk["ref_columns"] = list(tables.get(fk["ref_table"], {}).get("primary_key") or ["id"])
    return tables


def table_for_model(model, schema):
    """Table of the final schema that a query's model reference (`Order`, `models.Order`) points to; None if unknown."""
    mt = schema.get("model_tables", {})
    name = mt.get(model)
    cand = name if name else None
    names = list(schema["tables"])
    if cand:
        return next((n for n in names if fold(n) == fold(cand)), None)
    f = fold(model)
    return next((n for n in names if fold(n) in (f, fold(plural(model)), fold(singular(model)))), None)


def extract(sql_files, ast, R):
    """sql_files = [(relative path, text)]; ast = the ast_metrics.js output. Returns the normalized schema."""
    seq = ast.get("sequelize") or {"models": [], "associations": [], "migrations": []}
    sqlb = sql_builder(sql_files, R)
    migs = migrations_builder(seq.get("migrations", []), R)
    raw = sql_in_migrations(ast.get("sqlStrings", []), R)
    for path, text in raw:  # DDL in JS migrations: same parser, labelled as a migration
        tmp = Builder("sequelize_migration")
        tmp.tables = migs.tables
        apply_sql(tmp, text, path, R)
        migs.unparsed += tmp.unparsed
    modb, model_tables = models_builder(seq, R)
    order = {"sql": sqlb, "sequelize_migration": migs, "sequelize_model": modb}
    tables = merge([order[s] for s in R["source_preference"] if s in order], R)
    count = {}
    for t in tables.values():
        count[t["source"]] = count.get(t["source"], 0) + 1
    return {"tables": tables, "sources": count, "model_tables": model_tables,
            "unparsed": (sqlb.unparsed + migs.unparsed + modb.unparsed)[:40]}


def summary(schema):
    t = schema.get("tables", {})
    src = ", ".join(f"{n} from {s}" for s, n in sorted(schema.get("sources", {}).items()))
    return f"{len(t)} table(s)" + (f" ({src})" if src else "")
