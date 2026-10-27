"""Tests of the evaluator itself (no external dependencies):  python -m unittest discover -s tests -v

They cover the rules that weigh most on the results: level from criteria, rule S1192, layers (with doubtful classification and with no
inter-layer dependencies), reading node:test coverage, the DV8 matrix and Unhealthy Inheritance, and the extraction of the relational
schema (SQL, Sequelize migrations and models).
"""
import argparse, contextlib, io, json, os, subprocess, sys, tempfile, threading, unittest, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import evaluate as ev  # noqa: E402
import relational_schema as rs  # noqa: E402
import relational_analysis as ra  # noqa: E402
import dv8_metrics  # noqa: E402
import judge  # noqa: E402
import cli  # noqa: E402
import pg_analysis  # noqa: E402
import pg_runtime  # noqa: E402
import acceptance_check  # noqa: E402
import run_experiment  # noqa: E402


class Opts:
    accept_heuristics = False


def crit(**c):
    return {k: {"ok": v} for k, v in c.items()}


class TestLevel(unittest.TestCase):
    def test_all_meet(self):
        self.assertEqual(ev.level_from(crit(C1=True, C2=True)), ("Meets", "Meets", "Meets"))

    def test_half_is_partial_and_less_fails(self):
        self.assertEqual(ev.level_from(crit(C1=True, C2=False))[0], "Partial")
        self.assertEqual(ev.level_from(crit(C1=True, C2=False, C3=False))[0], "Fails")

    def test_pending_gives_a_range(self):
        level, lo, hi = ev.level_from(crit(C1=True, C2=None, C3=None))
        self.assertIsNone(level); self.assertEqual((lo, hi), ("Fails", "Meets"))

    def test_mandatory_criterion(self):
        self.assertEqual(ev.level_from(crit(C1=False, C2=True, C3=True), must=("C1",))[0], "Fails")


class TestConfigurationS1192(unittest.TestCase):
    def evaluate(self, occ):
        m = {"ast": {"networkLiterals": [], "files": [{"path": "a.js", "loc": 1000, "test": False}], "literalOccurrences": occ,
                     "envFiles": {"backend/src/config.js": 1}}, "env_example": True}
        return ev.eval_configuration(m, {}, Opts)[0]["C2"]

    def test_flags_long_literal_repeated_three_times(self):
        c = self.evaluate({"Server route not found here": ["a:1", "a:2", "a:3"]})
        self.assertFalse(c["ok"]); self.assertEqual(c["value"], {"Server route not found here": 3})

    def test_does_not_flag_single_words_ignored_literals_or_two_repetitions(self):
        c = self.evaluate({"shipped": ["a:1"] * 5, "application/json": ["a:1"] * 4, "Some long sample text": ["a:1", "a:2"]})
        self.assertTrue(c["ok"])


def module(src, targets):
    return {"source": src, "deps": [{"to": d, "local": True} for d in targets]}


class TestLayers(unittest.TestCase):
    def m(self, modules, layers, origin=None):
        return {"layers": layers, "layers_origin": origin or {}, "graph": {"modules": modules}}

    def test_no_inter_layer_dependencies_stays_pending(self):
        m = self.m([], {"a/controllers/x.js": "presentation", "a/services/y.js": "business"})
        crit_, _, _, _, forced = ev.eval_layers(m, {}, Opts)
        self.assertIsNone(crit_["C2"]["ok"]); self.assertEqual(forced, (None, "Fails", "Meets"))

    def test_manual_resolves_no_dependencies(self):
        m = self.m([], {"a/controllers/x.js": "presentation", "a/services/y.js": "business"})
        self.assertEqual(ev.eval_layers(m, {"layers": {"C2": {"ok": True}}}, Opts)[4], ("Meets",) * 3)
        self.assertEqual(ev.eval_layers(m, {"layers": {"C2": {"ok": False}}}, Opts)[4], ("Fails",) * 3)

    def _with_violation(self, origin_source):
        layers = {"p/c.js": "presentation", "n/s.js": "business", "d/m.js": "data"}
        mods = [module("p/c.js", ["n/s.js"] * 9), module("d/m.js", ["n/s.js"])]  # 1 violation (data→business) out of 10
        return self.m(mods, layers, {"d/m.js": origin_source, "n/s.js": "services", "p/c.js": "controllers"})

    def test_violation_with_ambiguous_directory_stays_pending(self):
        m = self._with_violation("domain")
        _, met, _, _, forced = ev.eval_layers(m, {}, Opts)
        self.assertEqual(met["doubtful_violations"], 1); self.assertEqual(forced, (None, "Fails", "Meets"))
        self.assertEqual(ev.eval_layers(m, {"layers": {"C2": {"ok": True}}}, Opts)[4], ("Meets",) * 3)
        self.assertEqual(ev.eval_layers(m, {"layers": {"C2": {"ok": False}}}, Opts)[4], ("Fails",) * 3)

    def test_firm_violation_fails(self):
        self.assertEqual(ev.eval_layers(self._with_violation("models"), {}, Opts)[4], ("Fails",) * 3)

    def test_no_violations_meets(self):
        m = self.m([module("p/c.js", ["n/s.js"] * 3), module("n/s.js", ["d/m.js"])],
                   {"p/c.js": "presentation", "n/s.js": "business", "d/m.js": "data"})
        self.assertEqual(ev.eval_layers(m, {}, Opts)[4], ("Meets",) * 3)


class TestCoverage(unittest.TestCase):
    def test_parse_lcov_adds_unloaded_files(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t); (d / "src").mkdir(); (d / "node_modules").mkdir()
            (d / "src" / "a.js").write_text("x\n" * 10); (d / "src" / "b.js").write_text("a\n\nb\nc\n")
            (d / "src" / "a.test.js").write_text("t\n"); (d / "node_modules" / "z.js").write_text("z\n")
            lcov = d / "lcov.info"
            lcov.write_text("SF:src/a.js\nLF:10\nLH:5\nBRF:4\nBRH:2\nend_of_record\n")
            r = ev.parse_lcov(lcov, d)
        self.assertEqual((r["lines_total"], r["lines_cov"], r["br_total"], r["br_cov"], r["unloaded"]), (13, 5, 4, 2, 1))


class TestDuplication(unittest.TestCase):
    def test_detects_clones_and_reports_paths_relative_to_the_app(self):
        with tempfile.TemporaryDirectory() as t:
            app = Path(t) / "app"; (app / "src").mkdir(parents=True); out = Path(t) / "out"; out.mkdir()
            body = "\n".join(f"  const v{i} = input.items.map((x) => x * {i}).filter(Boolean).reduce((a, b) => a + b, 0);" for i in range(12))
            for n in (1, 2):
                (app / "src" / f"dup{n}.js").write_text("function calc(input) {\n" + body + "\n  return v0;\n}\n")
            r = ev.run_duplication(app, out)
        self.assertTrue(r["ok"]); self.assertEqual(r["clones"], 1); self.assertGreater(r["pct"], 0)
        self.assertTrue(r["top"][0].startswith("src/dup"), r["top"])


class TestNewMeasures(unittest.TestCase):
    def test_eol_offline_returns_empty_and_online_returns_majors(self):
        self.assertEqual(ev.fetch_eol(True), {})
        r = ev.fetch_eol(False)
        for k, v in r.items():
            self.assertTrue(v and all(isinstance(x, int) for x in v), (k, v))

    def test_orphan_files_ignores_entry_points_and_tests(self):
        m = {"graph": {"modules": [{"source": "a.js", "deps": [{"to": "b.js", "local": True}]}]},
             "ast": {"files": [{"path": p, "test": t} for p, t in
                               [("a.js", False), ("b.js", False), ("c.js", False), ("server.js", False), ("c.test.js", True)]]}}
        self.assertEqual(ev.orphan_files(m), ["a.js", "c.js"])

    def test_supplementary_indicators(self):
        m = {"readme": "Install with npm install. Run with npm start.", "contract": {"properties": ["name"]},
             "ast": {"files": [{"path": "a.js", "loc": 100, "test": False, "frontend": False}, {"path": "a.test.js", "loc": 10, "test": True, "frontend": False}],
                     "imports": [], "testCases": [{"file": "a.test.js", "line": 1, "asserts": False}],
                     "docs": [{"file": "a.js", "line": 1, "name": "f", "documented": True}, {"file": "a.js", "line": 5, "name": "g", "documented": False}],
                     "components": [], "hooks": [], "security": {"evalCalls": [{"file": "a.js", "line": 3}], "secrets": [], "sqlInjection": []}},
             "schema": {"tables": {"items": {"columns": {"name": {"name": "name"}, "qty": {"name": "qty"}}}}}}
        r = {c["id"]: c for c in ev.supplementary_indicators(m)}
        self.assertEqual(r["tests_without_assertions"]["status"], "review")
        self.assertEqual(r["doc_jsdoc"]["value"], 50.0); self.assertEqual(r["doc_jsdoc"]["status"], "ok")
        self.assertEqual(r["sec_eval"]["value"], 1)
        self.assertEqual(r["contract_schema"]["value"], 50.0)
        self.assertNotIn("fe_props", r)

    def test_unhealthy_inheritance_by_graph(self):
        cls = [{"name": "Base", "file": "base.js", "extends": None}, {"name": "Child", "file": "child.js", "extends": "Base"}]
        mod = lambda s, *d: {"source": s, "deps": [{"to": x, "local": True} for x in d]}
        healthy = {"ast": {"classes": cls}, "graph": {"modules": [mod("child.js", "base.js")]}}
        self.assertEqual(ev.unhealthy_inheritance_graph(healthy), [])
        parent_imports_child = {"ast": {"classes": cls}, "graph": {"modules": [mod("base.js", "child.js"), mod("child.js", "base.js")]}}
        self.assertEqual(len(ev.unhealthy_inheritance_graph(parent_imports_child)), 1)
        client = {"ast": {"classes": cls}, "graph": {"modules": [mod("child.js", "base.js"), mod("app.js", "base.js", "child.js")]}}
        self.assertEqual(len(ev.unhealthy_inheritance_graph(client)), 1)

    def test_cliques_are_strongly_connected_components(self):
        mod = lambda s, *d: {"source": s, "deps": [{"to": x, "local": True} for x in d]}
        m = {"graph": {"modules": [mod("a", "b"), mod("b", "c"), mod("c", "a"), mod("d", "a")]}}
        self.assertEqual(ev.cliques(m), [["a", "b", "c"]])

    def test_observability_counts_authentication_and_writes(self):
        fn = lambda ev_, logs: {"event": ev_, "logs": logs, "file": "c.js", "line": 1, "name": "f"}
        m = {"app": ".", "packages": {"packages": [{"dependencies": {}, "devDependencies": {}}]},
             "ast": {"catchBlocks": {"total": 0, "logging": 0, "delegating": 0, "silent": []}, "errorMiddleware": [], "consoleCalls": [], "routes": [],
                     "functions": [fn("authentication", True), fn("write", False)]}}
        crit = ev.eval_observability(m, {}, Opts())[0]
        self.assertEqual(crit["C1"]["value"], 0.5); self.assertFalse(crit["C1"]["ok"])
        m["packages"]["packages"][0]["dependencies"] = {"morgan": "1"}
        self.assertEqual(ev.eval_observability(m, {}, Opts())[0]["C1"]["value"], 1.0)

    def test_naming_convention_helper(self):
        self.assertEqual(len(ev.mixed_naming_convention({"unit_price", "createdAt", "_id"})), 1)
        self.assertEqual(ev.mixed_naming_convention({"createdAt", "userId"}), [])


FIX = ROOT / "tests" / "fixtures"
RUBRIC_REL = ev.RUBRIC["relational"]


def extract_sql(text):
    return rs.extract([("x.sql", text)], {}, RUBRIC_REL)["tables"]


class TestSqlSchema(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.t = rs.extract([("schema_ok.sql", (FIX / "schema_ok.sql").read_text(encoding="utf-8"))], {}, RUBRIC_REL)

    def test_tables_columns_and_primary_keys(self):
        T = self.t["tables"]
        self.assertEqual(sorted(T), ["order_items", "orders", "products", "users"])
        self.assertEqual(T["users"]["primary_key"], ["id"]); self.assertEqual(T["order_items"]["primary_key"], ["order_id", "product_id"])
        c = T["products"]["columns"]
        self.assertEqual((c["price"]["type"], c["price"]["family"], c["price"]["nullable"]), ("numeric(10,2)", "numeric", False))
        self.assertTrue(c["description"]["nullable"]); self.assertEqual(c["id"]["family"], "integer")
        self.assertEqual(T["users"]["columns"]["id"]["family"], "integer"); self.assertFalse(T["users"]["columns"]["id"]["nullable"])  # serial
        self.assertEqual(T["orders"]["columns"]["status"]["default"], "'pending'")

    def test_foreign_keys_unique_checks_and_indexes_with_their_source(self):
        T = self.t["tables"]
        fks = {(tuple(f["columns"]), f["ref_table"], tuple(f["ref_columns"])) for t in T.values() for f in t["foreign_keys"]}
        self.assertEqual(fks, {(("user_id",), "users", ("id",)), (("order_id",), "orders", ("id",)), (("product_id",), "products", ("id",))})
        self.assertEqual(T["orders"]["foreign_keys"][0]["on_delete"], "CASCADE")
        self.assertEqual(T["users"]["unique"][0]["columns"], ["email"])
        self.assertEqual({tuple(c["columns"]) for c in T["products"]["checks"]}, {("price",), ("stock",)})
        self.assertEqual([i["columns"] for i in T["orders"]["indexes"]], [["user_id"]])
        self.assertEqual({el["source"] for t in T.values() for el in t["foreign_keys"] + t["indexes"]}, {"sql"})
        self.assertEqual(self.t["sources"], {"sql": 4})

    def test_alter_table_drop_and_comments_and_down_sections(self):
        T = extract_sql("""
            -- comment; with a semicolon
            CREATE TABLE "Weird Name" (id int PRIMARY KEY, "camelCol" text, note text DEFAULT 'a;b'); /* block; comment */
            CREATE TABLE a (id int, b_id int);
            ALTER TABLE a ADD COLUMN c numeric(5, 2) NOT NULL, ADD CONSTRAINT a_pk PRIMARY KEY (id);
            ALTER TABLE a ADD FOREIGN KEY (b_id) REFERENCES "Weird Name" (id);
            ALTER TABLE a ALTER COLUMN b_id SET NOT NULL;
            CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS a_c_uq ON a (lower(c::text), b_id DESC);
            CREATE TABLE gone (id int); DROP TABLE IF EXISTS gone;
            CREATE FUNCTION f() RETURNS void AS $$ BEGIN CREATE TABLE inside_function (x int); END $$ LANGUAGE plpgsql;
            -- migrate:down
            DROP TABLE a;
        """)
        self.assertEqual(sorted(T), ["Weird Name", "a"])  # quoted names keep their case; the DROP in the down section is ignored
        self.assertIn("camelCol", T["Weird Name"]["columns"]); self.assertEqual(T["Weird Name"]["columns"]["note"]["default"], "'a;b'")
        a = T["a"]
        self.assertEqual(a["primary_key"], ["id"]); self.assertEqual(a["columns"]["c"]["type"], "numeric(5,2)")
        self.assertFalse(a["columns"]["b_id"]["nullable"]); self.assertEqual(a["foreign_keys"][0]["ref_table"], "Weird Name")
        self.assertEqual(a["foreign_keys"][0]["ref_columns"], ["id"])
        self.assertTrue(a["indexes"][0]["unique"]); self.assertEqual(a["indexes"][0]["columns"], ["lower(c::text)", "b_id"])

    def test_inline_references_without_columns_resolve_to_the_target_primary_key(self):
        T = extract_sql("CREATE TABLE p (code text PRIMARY KEY); CREATE TABLE c (id int PRIMARY KEY, p_code text REFERENCES p);")
        self.assertEqual(T["c"]["foreign_keys"][0]["ref_columns"], ["code"])

    def test_down_files_and_ignored_tables(self):
        t = rs.extract([("001_up.sql", "CREATE TABLE a (id int PRIMARY KEY);"), ("001_down.sql", "DROP TABLE a;"),
                        ("002.sql", 'CREATE TABLE "SequelizeMeta" (name text PRIMARY KEY);')], {}, RUBRIC_REL)
        self.assertEqual(list(t["tables"]), ["a"])

    def test_type_families(self):
        fam = lambda x: rs.type_family(x, RUBRIC_REL)
        self.assertEqual([fam("VARCHAR(10)"), fam("double precision"), fam("timestamp with time zone"), fam("int4[]"), fam("jsonb"), fam("citext"), fam("UUID")],
                         ["string", "float", "timestamp", "array", "json", "string", "uuid"])
        self.assertIsNone(fam("geometry"))
        self.assertEqual(rs.sequelize_type({"$expr": "Sequelize.DECIMAL(10, 2)"}, RUBRIC_REL), "numeric(10,2)")
        self.assertEqual(rs.sequelize_type({"$expr": "DataTypes.ARRAY(DataTypes.TEXT)"}, RUBRIC_REL), "text[]")


class TestSequelizeSchema(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        out = Path(cls.tmp.name)
        cls.ast = ev.run_ast(FIX / "sequelize_app", out)
        cls.ast_models = ev.run_ast(FIX / "sequelize_models_only", out)
        cls.s = rs.extract([], cls.ast, RUBRIC_REL)
        cls.m = rs.extract([], cls.ast_models, RUBRIC_REL)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_migrations_decide_their_tables_and_models_fill_the_rest(self):
        T = self.s["tables"]
        self.assertEqual({n: t["source"] for n, t in T.items()},
                         {"users": "sequelize_migration", "orders": "sequelize_migration", "order_items": "sequelize_migration", "Coupons": "sequelize_model"})
        self.assertEqual(self.s["sources"], {"sequelize_migration": 3, "sequelize_model": 1})
        # the model of `users` says email is nullable; the migration (higher preference) says NOT NULL
        self.assertFalse(T["users"]["columns"]["email"]["nullable"])

    def test_migration_operations_createTable_addConstraint_addIndex_and_down_ignored(self):
        T = self.s["tables"]
        self.assertEqual(T["order_items"]["primary_key"], ["order_id", "product_ref"])  # addConstraint 'primary key'
        self.assertEqual([(f["columns"], f["ref_table"], f["source"]) for f in T["order_items"]["foreign_keys"]],
                         [(["order_id"], "orders", "sequelize_migration")])
        self.assertEqual(T["orders"]["checks"][0]["columns"], ["total"])
        self.assertEqual([i["columns"] for i in T["orders"]["indexes"]], [["user_id"]])  # removeIndex lives in `down`: ignored
        self.assertEqual(T["orders"]["columns"]["total"]["type"], "numeric(12,2)")
        self.assertEqual(T["orders"]["foreign_keys"][0]["on_delete"], "CASCADE")
        self.assertEqual(T["users"]["columns"]["name"]["type"], "varchar(100)"); self.assertIn("users", T)  # dropTable in `down` ignored

    def test_model_only_table_gets_timestamps_default_pk_and_association_columns(self):
        c = self.s["tables"]["Coupons"]
        self.assertEqual(c["primary_key"], ["id"]); self.assertIn("createdAt", c["columns"])
        self.assertEqual([(f["columns"], f["ref_table"], f["source"]) for f in c["foreign_keys"]], [(["UserId"], "users", "sequelize_model")])
        self.assertEqual(self.s["model_tables"]["Order"], "orders")

    def test_models_only_app_belongsToMany_hasMany_and_belongsTo(self):
        T = self.m["tables"]
        self.assertEqual(sorted(T), ["Courses", "Enrollments", "Students", "Teachers"])
        self.assertEqual(T["Enrollments"]["primary_key"], ["StudentId", "CourseId"])
        self.assertEqual({(f["columns"][0], f["ref_table"]) for f in T["Enrollments"]["foreign_keys"]}, {("StudentId", "Students"), ("CourseId", "Courses")})
        self.assertEqual([(f["columns"], f["ref_table"]) for f in T["Courses"]["foreign_keys"]], [(["teacherId"], "Teachers")])  # hasMany + belongsTo: one FK
        self.assertNotIn("createdAt", T["Teachers"]["columns"])  # timestamps: false
        self.assertEqual(T["Courses"]["columns"]["price"]["family"], "float")

    def test_query_filters_and_sql_strings_from_the_ast(self):
        q = {(x["model"], x["call"]): x for x in self.ast["queryFields"]}
        self.assertEqual(q[("Order", "findAll")]["fields"], ["user_id"]); self.assertEqual(q[("Order", "findAll")]["sort"], ["created_at"])
        self.assertEqual(q[("User", "findOne")]["fields"], ["email", "name"])  # Op.or branches are walked
        self.assertEqual(len(self.ast["security"]["sqlInjection"]), 1)  # only the template with ${} (the :named one is parameterized)
        self.assertEqual(rs.table_for_model("Order", self.s), "orders"); self.assertEqual(rs.table_for_model("Coupon", self.s), "Coupons")
        self.assertIsNone(rs.table_for_model("orderRepository", self.s))

    def test_no_relational_schema_means_no_tables(self):
        self.assertEqual(rs.extract([], {}, RUBRIC_REL)["tables"], {})


def er_from(text):
    if text is None:
        return {"found": False, "diagram": False, "file": None, "entities": {}, "relationships": [], "text": ""}
    return {"found": True, "diagram": True, "file": "docs/entity-relationship-model.md", "text": text, **ra.parse_er(text)}


def dm_model(sql, er_text=None, queries=(), readme="", pg=None):
    """Minimal evidence for eval_data_model: a schema from SQL, the parsed ER, raw SQL strings that stand for the code's queries."""
    m = {"schema": rs.extract([("s.sql", sql)], {}, RUBRIC_REL), "er": er_from(er_text), "readme": readme,
         "ast": {"queryFields": [], "sqlStrings": [{"file": "svc.js", "line": i + 1, "text": q} for i, q in enumerate(queries)]}}
    if pg:
        m["pg"] = pg
    return m


OK_SQL = (FIX / "schema_ok.sql").read_text(encoding="utf-8")
WEAK_SQL = (FIX / "schema_weak.sql").read_text(encoding="utf-8")
ER_MATCH = (FIX / "er_match.md").read_text(encoding="utf-8")
ER_MISMATCH = (FIX / "er_mismatch.md").read_text(encoding="utf-8")
GOOD_QUERIES = ["SELECT * FROM orders WHERE user_id = $1", "SELECT * FROM users u WHERE u.email = $1"]


class AcceptHeuristics:
    accept_heuristics = True


class TestErModel(unittest.TestCase):
    def test_parser_reads_entities_attributes_keys_and_cardinalities(self):
        er = ra.parse_er(ER_MATCH)
        self.assertEqual(sorted(er["entities"]), ["ORDERS", "ORDER_ITEMS", "PRODUCTS", "USERS"])
        a = {x["name"]: x for x in er["entities"]["ORDER_ITEMS"]["attributes"]}
        self.assertEqual(a["order_id"]["keys"], ["PK", "FK"]); self.assertEqual(a["unit_price"]["type"], "decimal")
        self.assertEqual({x["name"]: x["keys"] for x in er["entities"]["USERS"]["attributes"]}["email"], ["UK"])
        self.assertEqual(er["entities"]["USERS"]["attributes"][1]["comment"], "not null")
        r = {(x["left"], x["right"]): x for x in er["relationships"]}
        self.assertEqual(r[("USERS", "ORDERS")]["right_card"], "o{"); self.assertEqual(r[("PRODUCTS", "ORDER_ITEMS")]["label"], "appears in")
        self.assertEqual(len(er["relationships"]), 3)

    def test_parser_handles_aliases_quotes_unfenced_diagrams_and_no_diagram(self):
        er = ra.parse_er('erDiagram\n  p["Product Item"] {\n    int id PK\n  }\n  "Order" ||--o{ p : has\n')
        self.assertEqual(er["entities"]["p"]["alias"], "Product Item"); self.assertIn("Order", er["entities"])
        self.assertEqual(ra.parse_er("# only prose, no diagram"), {"entities": {}, "relationships": []})
        self.assertEqual(ra.card_flags("}|"), (True, False)); self.assertEqual(ra.card_flags("|o"), (False, True)); self.assertEqual(ra.card_flags("||"), (False, False))

    def test_matching_er_has_no_mismatch(self):
        c = ra.compare_er(er_from(ER_MATCH), dm_model(OK_SQL)["schema"], RUBRIC_REL)
        self.assertTrue(c["matches"], c); self.assertEqual(c["mismatches"], 0)

    def test_non_matching_er_reports_each_kind_of_difference(self):
        c = ra.compare_er(er_from(ER_MISMATCH), dm_model(OK_SQL)["schema"], RUBRIC_REL)
        self.assertFalse(c["matches"])
        self.assertEqual(c["entities_not_in_schema"], ["COUPON"])
        self.assertEqual(c["attributes_missing_in_er"], {"users": ["password_hash"]}); self.assertEqual(c["attributes_not_in_schema"], {"users": ["phone"]})
        self.assertEqual(c["pk_mismatch"]["order_items"], {"schema": ["order_id", "product_id"], "er": []})
        self.assertEqual(c["fk_mismatch"]["orders"], {"schema": ["user_id"], "er": []})  # user_id is not marked FK in the ER
        self.assertEqual(c["relationships_missing_in_er"], ["order_items → products"]); self.assertEqual(c["relationships_not_in_schema"], ["COUPON — ORDER"])
        self.assertEqual(c["cardinality_mismatch"], [])  # ORDER_ITEM }o--|| ORDER is many-to-one with ORDER on the 'one' side: fine
        self.assertEqual(c["type_differences"], ["products.price: ER float vs schema numeric(10,2)"])

    def test_inverted_cardinality_is_a_mismatch(self):
        er = ER_MATCH.replace("ORDERS ||--|{ ORDER_ITEMS", "ORDERS }|--|| ORDER_ITEMS")
        c = ra.compare_er(er_from(er), dm_model(OK_SQL)["schema"], RUBRIC_REL)
        self.assertEqual(len(c["cardinality_mismatch"]), 1); self.assertIn("order_items → orders", c["cardinality_mismatch"][0])

    def test_load_er_finds_the_file_case_insensitively(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertFalse(ra.load_er(t, RUBRIC_REL)["found"])
            (Path(t) / "docs").mkdir(); (Path(t) / "docs" / "Entity-Relationship-Model.md").write_text(ER_MATCH, encoding="utf-8")
            er = ra.load_er(t, RUBRIC_REL)
            self.assertTrue(er["found"] and er["diagram"]); self.assertEqual(len(er["entities"]), 4)
            (Path(t) / "docs" / "Entity-Relationship-Model.md").write_text("# no diagram yet", encoding="utf-8")
            er = ra.load_er(t, RUBRIC_REL)
            self.assertTrue(er["found"]); self.assertFalse(er["diagram"])


class TestDataModelCriteria(unittest.TestCase):
    def crit(self, m, opts=Opts):
        return ev.eval_data_model(m, {}, opts())[0]

    def ok_values(self, crit):
        return {k: v["ok"] for k, v in crit.items()}

    def test_meets_when_everything_holds_and_heuristics_are_accepted(self):
        c = self.crit(dm_model(OK_SQL, ER_MATCH, GOOD_QUERIES), AcceptHeuristics)
        self.assertEqual(self.ok_values(c), dict.fromkeys(["C1", "C2", "C3", "C4", "C5", "C6"], True))
        self.assertEqual(ev.level_from(c)[0], "Meets")
        self.assertEqual(c["C3"]["value"]["constrained_columns"], "13/14 = 93%")

    def test_suggestions_do_not_count_without_accepting_heuristics_and_leave_a_range(self):
        c = self.crit(dm_model(OK_SQL, ER_MATCH, GOOD_QUERIES))
        self.assertEqual((c["C2"]["ok"], c["C5"]["ok"]), (None, None))
        self.assertEqual((c["C2"]["suggested"], c["C5"]["suggested"]), (True, True)); self.assertEqual(c["C2"]["source"], "heuristic")
        self.assertEqual([c[k]["ok"] for k in ("C1", "C3", "C4", "C6")], [True] * 4)
        level, lo, hi = ev.level_from(c)
        self.assertIsNone(level); self.assertEqual((lo, hi), ("Partial", "Meets"))  # 4 of 6 met for sure; the 2 suggestions decide the rest

    def test_partial_when_half_or_more_are_met(self):
        c = self.crit(dm_model(OK_SQL, ER_MISMATCH, GOOD_QUERIES + ["SELECT * FROM orders WHERE status = $1"]), AcceptHeuristics)
        self.assertEqual(self.ok_values(c), {"C1": True, "C2": True, "C3": True, "C4": False, "C5": True, "C6": False})
        self.assertEqual(ev.level_from(c)[0], "Partial")

    def test_fails_when_fewer_than_half_are_met(self):
        c = self.crit(dm_model(WEAK_SQL, None, ["SELECT * FROM orders WHERE user_id = $1"]), AcceptHeuristics)
        v = self.ok_values(c)
        self.assertEqual((v["C1"], v["C3"], v["C4"], v["C6"]), (False, False, False, False))
        self.assertEqual(ev.level_from(c)[0], "Fails")

    def test_c1_reports_tables_without_pk_and_implicit_relations(self):
        v = self.crit(dm_model(WEAK_SQL))["C1"]["value"]
        self.assertEqual(v["without_primary_key"], ["audit_log"]); self.assertEqual(v["implicit_relations"], ["audit_log.user_id", "orders.user_id"])
        self.assertFalse(self.crit(dm_model("CREATE TABLE a (id int PRIMARY KEY, b_id int);"))["C1"]["ok"])
        self.assertTrue(self.crit(dm_model("CREATE TABLE a (b_id int PRIMARY KEY); CREATE TABLE c (id int PRIMARY KEY, a_id int REFERENCES a (b_id));"))["C1"]["ok"])
        self.assertTrue(self.crit(dm_model('CREATE TABLE a ("userId" int PRIMARY KEY, x text NOT NULL);'))["C1"]["ok"])  # the table's own key is not an implicit relation
        self.assertFalse(self.crit(dm_model('CREATE TABLE a (id int PRIMARY KEY, "userId" int);'))["C1"]["ok"])  # camelCase *Id too

    def test_c3_needs_enough_constraints_and_no_float_money(self):
        c3 = self.crit(dm_model("CREATE TABLE p (id int PRIMARY KEY, name text NOT NULL, price float NOT NULL, note text);"))["C3"]
        self.assertFalse(c3["ok"]); self.assertEqual(c3["value"]["float_money_columns"], ["p.price (float)"])  # 2/3 constrained, but FLOAT for money
        c3 = self.crit(dm_model("CREATE TABLE p (id int PRIMARY KEY, name text, price numeric(10,2) NOT NULL, note text);"))["C3"]
        self.assertFalse(c3["ok"]); self.assertEqual(c3["value"]["constrained_columns"], "1/3 = 33%")  # NUMERIC is right, but too few constraints
        c3 = self.crit(dm_model("CREATE TABLE p (id int PRIMARY KEY, name text NOT NULL, price numeric(10,2) NOT NULL, note text);"))["C3"]
        self.assertTrue(c3["ok"]); self.assertEqual(c3["value"]["float_money_columns"], [])

    def test_c3_threshold_is_read_from_the_rubric(self):
        sql = "CREATE TABLE p (id int PRIMARY KEY, a text NOT NULL, b text, c text, d text);"
        self.assertFalse(self.crit(dm_model(sql))["C3"]["ok"])  # 1 of 4 = 25% < 50%
        sql = "CREATE TABLE p (id int PRIMARY KEY, a text NOT NULL, b text NOT NULL, c text, d text);"
        self.assertTrue(self.crit(dm_model(sql))["C3"]["ok"])  # 50%
        self.assertEqual(ev.RUBRIC["thresholds"]["data_model"]["constraints_min_pct"], 50.0)

    def test_c3_lists_natural_keys_without_unique_but_does_not_fail_on_them(self):
        c3 = self.crit(dm_model("CREATE TABLE u (id int PRIMARY KEY, email text NOT NULL, name text NOT NULL);"))["C3"]
        self.assertTrue(c3["ok"]); self.assertEqual(c3["value"]["natural_keys_without_unique"], ["u.email"])

    def test_c4_foreign_keys_and_filters_need_an_index(self):
        no_idx = OK_SQL.replace("CREATE INDEX orders_user_id_idx ON orders (user_id);", "")
        c4 = self.crit(dm_model(no_idx, queries=GOOD_QUERIES))["C4"]
        self.assertFalse(c4["ok"]); self.assertEqual(c4["value"]["fks_without_index"], ["orders(user_id)"])
        self.assertEqual(c4["value"]["unindexed_queries"], [x for x in c4["value"]["unindexed_queries"] if x.startswith("orders.where(user_id)")])
        self.assertTrue(self.crit(dm_model(OK_SQL, queries=GOOD_QUERIES))["C4"]["ok"])  # composite PK (order_id, product_id) serves the FK on order_id
        bad = self.crit(dm_model(OK_SQL, queries=GOOD_QUERIES + ["UPDATE orders SET total = 0 WHERE status = 'x'"]))["C4"]
        self.assertFalse(bad["ok"]); self.assertEqual(bad["value"]["unindexed_queries_pct"], 33.3)
        pk_only = self.crit(dm_model(OK_SQL, queries=["SELECT * FROM users WHERE id = $1"]))["C4"]
        self.assertTrue(pk_only["ok"]); self.assertEqual(pk_only["value"]["distinct_queries"], 0)  # filtering by the primary key is not a shape to check

    def test_c4_uses_sequelize_where_filters_from_the_ast(self):
        m = dm_model(OK_SQL)
        m["schema"]["model_tables"] = {"Order": "orders"}
        m["ast"]["queryFields"] = [{"file": "o.js", "line": 3, "model": "Order", "call": "findAll", "fields": ["userId"], "sort": [], "inLoop": False},
                                   {"file": "o.js", "line": 9, "model": "Order", "call": "findOne", "fields": ["total"], "sort": [], "inLoop": False},
                                   {"file": "o.js", "line": 9, "model": "Unknown", "call": "findOne", "fields": ["x"], "sort": [], "inLoop": False}]
        c4 = self.crit(m)["C4"]
        self.assertEqual(c4["value"]["unindexed_queries"], ["orders.where(total) in o.js:9"])  # userId resolves to user_id, which is indexed
        self.assertEqual(c4["value"]["unresolved_queries"], 1)

    def test_c2_suggestion_flags_repeating_groups_unjustified_copies_and_n_plus_one(self):
        base = "CREATE TABLE products (id int PRIMARY KEY, name text NOT NULL); "
        copy = base + "CREATE TABLE lines (id int PRIMARY KEY, product_id int NOT NULL REFERENCES products (id), product_name text NOT NULL);"
        c2 = self.crit(dm_model(copy))["C2"]
        self.assertFalse(c2["suggested"]); self.assertEqual(c2["value"]["denormalized_copies"], [{"copy": "lines.product_name", "of": "products.name", "justified": False}])
        justified = self.crit(dm_model(copy, readme="lines.product_name is a snapshot of the name at the time of purchase."))["C2"]
        self.assertTrue(justified["suggested"])
        groups = self.crit(dm_model("CREATE TABLE c (id int PRIMARY KEY, phone1 text, phone2 text);"))["C2"]
        self.assertFalse(groups["suggested"]); self.assertEqual(groups["value"]["repeating_groups"], ["c: phone1, phone2"])
        m = dm_model(OK_SQL); m["schema"]["model_tables"] = {"Order": "orders"}
        m["ast"]["queryFields"] = [{"file": "s.js", "line": 4, "model": "Order", "call": "findAll", "fields": [], "sort": [], "inLoop": True}]
        self.assertFalse(self.crit(m)["C2"]["suggested"])

    def test_c5_suggestion_flags_type_conflicts_duplicates_and_mixed_naming(self):
        conflict = "CREATE TABLE a (id int PRIMARY KEY, qty integer); CREATE TABLE b (id int PRIMARY KEY, qty text);"
        c5 = self.crit(dm_model(conflict))["C5"]
        self.assertFalse(c5["suggested"]); self.assertEqual(len(c5["value"]["conflicts"]), 1); self.assertIn("qty", c5["value"]["conflicts"][0])
        dup = "CREATE TABLE a (id int PRIMARY KEY, x text, y text); CREATE TABLE b (id int PRIMARY KEY, x text, y text);"
        self.assertEqual(self.crit(dm_model(dup))["C5"]["value"]["duplicate_tables"], ["a = b"])
        mixed = 'CREATE TABLE a (id int PRIMARY KEY, unit_price int, "createdAt" text);'
        self.assertTrue(any("mixed naming" in x for x in self.crit(dm_model(mixed))["C5"]["value"]["conflicts"]))
        self.assertTrue(self.crit(dm_model(OK_SQL))["C5"]["suggested"])

    def test_c6_missing_er_or_missing_diagram_fails(self):
        c6 = self.crit(dm_model(OK_SQL))["C6"]
        self.assertFalse(c6["ok"]); self.assertIn("not found", c6["value"])
        m = dm_model(OK_SQL, "no diagram here"); m["er"]["diagram"] = False
        self.assertIn("no Mermaid erDiagram", self.crit(m)["C6"]["value"])
        self.assertFalse(self.crit(m)["C6"]["ok"])
        mismatch = self.crit(dm_model(OK_SQL, ER_MISMATCH))["C6"]
        self.assertFalse(mismatch["ok"]); self.assertIn("entities_not_in_schema", mismatch["value"])

    def test_manual_review_can_decide_any_criterion_and_overrides_the_suggestion(self):
        m = dm_model(OK_SQL, ER_MATCH, GOOD_QUERIES)
        c = ev.eval_data_model(m, {"data_model": {"C2": {"ok": False, "note": "N+1 on checkout"}}}, Opts())[0]
        self.assertFalse(c["C2"]["ok"]); self.assertEqual((c["C2"]["source"], c["C2"]["value"]), ("manual", "N+1 on checkout"))

    def test_live_database_catalog_decides_c1_c3_c4_and_c6(self):
        # The static schema (no FK on orders.user_id) says C1 fails; the real database has the FK and its index: the catalog wins.
        static_sql = OK_SQL.replace("user_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,", "user_id INTEGER NOT NULL,")
        self.assertFalse(self.crit(dm_model(static_sql, ER_MATCH, GOOD_QUERIES))["C1"]["ok"])
        cat = json.loads((FIX / "pg_catalog_ok.json").read_text(encoding="utf-8"))
        c = self.crit(dm_model(static_sql, ER_MATCH, GOOD_QUERIES, pg=cat))
        self.assertEqual([c[k]["ok"] for k in ("C1", "C3", "C4", "C6")], [True] * 4)
        self.assertEqual({c[k]["source"] for k in ("C1", "C3", "C4", "C6")}, {"auto (live database)"})
        pts = ev.eval_data_model(dm_model(static_sql, ER_MATCH, GOOD_QUERIES, pg=cat), {}, Opts())
        self.assertTrue(pts[1]["live_database"])

    def test_live_catalog_tables_of_the_migration_tool_are_ignored(self):
        cat = {"tables": {"SequelizeMeta": {"columns": {"name": {"name": "name", "type": "character varying(255)", "nullable": False, "default": None}},
                                            "primary_key": ["name"], "foreign_keys": [], "unique": [], "checks": [], "indexes": []}}}
        self.assertEqual(ra.from_catalog(cat, RUBRIC_REL)["tables"], {})

    def test_an_empty_schema_means_the_data_schema_artifact_is_missing(self):
        a = {x["id"]: x for x in ev.inventory_artifacts(artifact_model(schema={"tables": {}, "sources": {}}), [])}
        self.assertFalse(a["data_schema"]["present"])
        self.assertIn("no relational schema", a["data_schema"]["detail"])


class TestLiveCatalog(unittest.TestCase):
    """Real catalogs (recorded from PostgreSQL 18.6 with pg_schema.js) stand in for a running server: no PostgreSQL or Docker needed."""
    def crit(self, m):
        return ev.eval_data_model(m, {}, Opts())

    def test_good_catalog_meets_the_measured_criteria_and_reports_index_usage(self):
        cat = json.loads((FIX / "pg_catalog_ok.json").read_text(encoding="utf-8"))
        crit, met, _, finding, _ = self.crit(dm_model(OK_SQL, ER_MATCH, GOOD_QUERIES, pg=cat))
        self.assertEqual([crit[k]["ok"] for k in ("C1", "C3", "C4", "C6")], [True] * 4)
        self.assertTrue(met["live_database"]); self.assertIn("live database", finding)
        self.assertEqual(met["unused_indexes"], ["order_items.idx_order_items_product", "orders.orders_user_id_idx"])  # idx_scan = 0 (informational)
        self.assertEqual(crit["C3"]["value"]["constrained_columns"], "13/14 = 93%")

    def test_weak_catalog_fails_c1_c3_and_c4(self):
        cat = json.loads((FIX / "pg_catalog_weak.json").read_text(encoding="utf-8"))
        crit = self.crit(dm_model(OK_SQL, ER_MATCH, ["SELECT * FROM orders WHERE user_id = $1"], pg=cat))[0]
        self.assertEqual(crit["C1"]["value"]["without_primary_key"], ["audit_log"])
        self.assertEqual(crit["C1"]["value"]["implicit_relations"], ["audit_log.user_id", "orders.user_id"])
        self.assertEqual([crit[k]["ok"] for k in ("C1", "C3", "C4", "C6")], [False] * 4)
        self.assertEqual(crit["C3"]["value"]["float_money_columns"], ["orders.total (double precision)"])

    def test_catalog_types_map_to_the_same_families_as_the_static_schema(self):
        live = ra.from_catalog(json.loads((FIX / "pg_catalog_ok.json").read_text(encoding="utf-8")), RUBRIC_REL)
        static = dm_model(OK_SQL)["schema"]
        fam = lambda sc: {(t, c): d["family"] for t, tb in sc["tables"].items() for c, d in tb["columns"].items()}
        self.assertEqual(fam(live), fam(static))

    def test_load_pg_reads_the_dump_next_to_the_results_and_forgets_it_when_absent(self):
        with tempfile.TemporaryDirectory() as t:
            m = {}
            self.assertNotIn("pg", ev.load_pg(t, m))
            (Path(t) / "pg_schema.json").write_text(json.dumps({"tables": {}}), encoding="utf-8")
            self.assertEqual(ev.load_pg(t, m)["pg"], {"tables": {}})
            (Path(t) / "pg_schema.json").unlink()
            self.assertNotIn("pg", ev.load_pg(t, m))


class TestPgRuntime(unittest.TestCase):
    def test_database_names_are_always_eval_prefixed_and_validated(self):
        self.assertEqual(pg_runtime.eval_db_name("claude-n1-ecommerce-r1"), "eval_claude_n1_ecommerce_r1")
        self.assertEqual(pg_runtime.eval_db_name("My App; DROP"), "eval_my_app_drop")
        self.assertTrue(len(pg_runtime.eval_db_name("x" * 200)) <= 55)
        self.assertTrue(pg_runtime.valid_eval_db("eval_a_1")); self.assertFalse(pg_runtime.valid_eval_db("postgres")); self.assertFalse(pg_runtime.valid_eval_db("eval_A"))
        self.assertFalse(pg_runtime.valid_eval_db("eval_a; DROP DATABASE x"))

    def test_db_url_keeps_credentials_and_query_and_masking_hides_the_password(self):
        url = pg_runtime.db_url("postgres://eva:p%40ss@db.example:5433/postgres?sslmode=require", "eval_x")
        self.assertEqual(url, "postgres://eva:p%40ss@db.example:5433/eval_x?sslmode=require")
        self.assertEqual(pg_runtime.password_of(url), "p@ss")
        self.assertEqual(pg_runtime.mask("connect eva:p@ss failed", url), "connect eva:*** failed")
        self.assertEqual(pg_runtime.build_url("u", "p w", "127.0.0.1", 5432, "eval_a"), "postgresql://u:p%20w@127.0.0.1:5432/eval_a")


class TestPgSchemaScript(unittest.TestCase):
    def node(self, code):
        p = subprocess.run(["node", "-e", code], cwd=ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout)

    def test_name_guard_url_and_type_formatting(self):
        r = self.node("const m=require('./pg_schema.js');console.log(JSON.stringify([m.validDbName('eval_a_b'),m.validDbName('postgres'),m.validDbName('eval_A'),"
                      "m.urlFor('postgres://u:p@h:5/postgres?sslmode=require','eval_x'),m.quoteIdent('a\"b'),"
                      "m.typeOf({data_type:'character varying',character_maximum_length:50}),m.typeOf({data_type:'numeric',numeric_precision:10,numeric_scale:2}),"
                      "m.typeOf({data_type:'ARRAY',udt_name:'_text'}),m.typeOf({data_type:'USER-DEFINED',udt_name:'order_status'}),m.typeOf({data_type:'integer',numeric_precision:32})]))")
        self.assertEqual(r, [True, False, False, "postgres://u:p@h:5/eval_x?sslmode=require", '"a""b"', "character varying(50)", "numeric(10,2)", "text[]", "order_status", "integer"])

    def test_the_cli_refuses_databases_that_are_not_eval(self):
        for cmd in ("create", "drop"):
            p = subprocess.run(["node", "pg_schema.js", cmd, "production"], cwd=ROOT, capture_output=True, text=True, timeout=60,
                               env={**os.environ, "PG_ADMIN_URL": "postgres://u:p@127.0.0.1:1/postgres"})
            self.assertEqual(p.returncode, 2); self.assertIn("only databases named eval_", p.stderr)

    def test_dump_catalog_maps_constraints_indexes_and_quotes(self):
        script = r"""
const {dumpCatalog}=require('./pg_schema.js');
const client={async query(text){
  if(/SHOW server_version/.test(text))return{rows:[{server_version:'16.4'}]};
  if(/current_database/.test(text))return{rows:[{name:'eval_t'}]};
  if(/information_schema\.columns/.test(text))return{rows:[
    {table_name:'orders',column_name:'id',data_type:'integer',is_nullable:'NO',column_default:null,is_identity:'YES'},
    {table_name:'orders',column_name:'user_id',data_type:'integer',is_nullable:'YES',column_default:null,is_identity:'NO'}]};
  if(/pg_constraint/.test(text))return{rows:[
    {name:'orders_pkey',kind:'p',table_name:'orders',columns:['id'],ref_columns:[],definition:'PRIMARY KEY (id)'},
    {name:'orders_user_fk',kind:'f',table_name:'orders',columns:['user_id'],ref_table:'users',ref_columns:['id'],on_delete:'c',definition:''},
    {name:'orders_chk',kind:'c',table_name:'orders',columns:['id'],ref_columns:[],definition:'CHECK ((id > 0))'}]};
  if(/pg_index/.test(text))return{rows:[{table_name:'orders',name:'orders_user_idx',is_unique:false,is_primary:false,is_valid:true,method:'btree',predicate:null,scans:3,columns:['"userId"']}]};
  if(/count\(\*\)/.test(text))return{rows:[{n:7}]};
  throw new Error('unexpected query '+text);}};
dumpCatalog(client).then(c=>console.log(JSON.stringify(c)));"""
        c = self.node(script)["tables"]["orders"]
        self.assertEqual((c["primary_key"], c["rows"]), (["id"], 7))
        self.assertEqual(c["columns"]["id"]["default"], "identity"); self.assertTrue(c["columns"]["user_id"]["nullable"])
        self.assertEqual(c["foreign_keys"], [{"name": "orders_user_fk", "columns": ["user_id"], "ref_table": "users", "ref_columns": ["id"], "on_delete": "CASCADE"}])
        self.assertEqual(c["checks"][0]["expr"], "CHECK ((id > 0))")
        self.assertEqual(c["indexes"][0]["columns"], ["userId"]); self.assertEqual(c["indexes"][0]["scans"], 3)


class TestPgAnalysisFlow(unittest.TestCase):
    """The orchestration of pg_analysis.py with the database and the backend replaced by mocks."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        (t / "app" / "backend").mkdir(parents=True)
        self.res = t / "results" / "claude-n1-ecommerce-r1"
        self.res.mkdir(parents=True)
        (self.res / "meta.json").write_text(json.dumps({"run_id": "claude-n1-ecommerce-r1"}), encoding="utf-8")
        (self.res / "metrics.json").write_text(json.dumps({"app": str(t / "app")}), encoding="utf-8")
        self.calls = []

    def tearDown(self):
        self.tmp.cleanup()

    def fake_node(self, fail=(), tables=True):
        def node_pg(args, admin_url, timeout=300):
            self.calls.append(args[0])
            if args[0] in fail:
                return 1, "boom"
            if args[0] == "dump":
                Path(args[2]).write_text(json.dumps({"tables": {"t": {}} if tables else {}}), encoding="utf-8")
            return 0, args[0] + " ok"
        return node_pg

    def run_flow(self, node, backend_error=None, **kw):
        seen = {}
        def exercise(be, env, port, res, wait, skip_seed, log):
            seen["env"] = env
            return backend_error
        with mock.patch.object(pg_analysis, "node_pg", node), mock.patch.object(pg_analysis, "exercise_backend", exercise), \
                mock.patch.dict(os.environ, {"PG_ADMIN_URL": "postgres://admin:topsecret@h:5432/postgres"}), contextlib.redirect_stdout(io.StringIO()):
            err, db = pg_analysis.analyze(self.res, "postgres://admin:topsecret@h:5432/postgres", **kw)
        return err, db, seen

    def test_creates_dumps_and_drops_the_database_and_hides_the_admin_url_from_the_app(self):
        err, db, seen = self.run_flow(self.fake_node())
        self.assertIsNone(err); self.assertEqual(db, "eval_claude_n1_ecommerce_r1"); self.assertEqual(self.calls, ["create", "dump", "drop"])
        self.assertTrue((self.res / "pg_schema.json").exists())
        self.assertNotIn("PG_ADMIN_URL", seen["env"])
        self.assertEqual(seen["env"]["DATABASE_URL"], "postgres://admin:topsecret@h:5432/eval_claude_n1_ecommerce_r1"); self.assertIn("PORT", seen["env"])

    def test_drops_the_database_even_when_the_backend_fails(self):
        err, _, _ = self.run_flow(self.fake_node(), backend_error="the backend did not open the port")
        self.assertIn("did not open the port", err); self.assertEqual(self.calls, ["create", "drop"])
        self.assertFalse((self.res / "pg_schema.json").exists())

    def test_keep_leaves_the_database_and_a_failed_create_drops_nothing(self):
        self.run_flow(self.fake_node(), keep=True)
        self.assertEqual(self.calls, ["create", "dump"])
        self.calls.clear()
        err, _, _ = self.run_flow(self.fake_node(fail=("create",)))
        self.assertIn("could not create", err); self.assertEqual(self.calls, ["create"])

    def test_an_empty_catalog_falls_back_to_the_static_analysis_and_a_failed_drop_is_reported(self):
        err, _, _ = self.run_flow(self.fake_node(tables=False))
        self.assertIn("no tables", err); self.assertFalse((self.res / "pg_schema.json").exists())
        err, _, _ = self.run_flow(self.fake_node(fail=("drop",)))
        self.assertIn("COULD NOT DROP eval_claude_n1_ecommerce_r1", err)


class ReferenceShop:
    """In-memory implementation of the minimum HTTP interface of requirements-ecommerce.md (no database, no Docker), used to test the gate.
    `money_as_string` and `object_ids` reproduce the two typical deviations the gate must catch."""
    def __init__(self, money_as_string=False, object_ids=False):
        self.money_as_string, self.object_ids = money_as_string, object_ids
        self.next_id = 0
        self.products = {n: {"id": self.new_id(), "name": n, "price": pr, "description": "d", "imageUrl": "u", "stock": st}
                         for n, pr, st in (("T-shirt", 10.0, 20), ("Mug", 5.0, 2), ("Book", 20.0, 50))}
        self.users, self.tokens, self.orders = {}, {}, {}

    def new_id(self):
        self.next_id += 1
        return uuid.uuid4().hex[:24] if self.object_ids else self.next_id

    def money(self, x):
        return f"{x:.2f}" if self.money_as_string else x

    def line(self, item):
        p = next(p for p in self.products.values() if p["id"] == item["productId"])
        gross = p["price"] * item["quantity"]
        total = round(gross * (0.9 if item["quantity"] >= 3 else 1.0), 2)
        return p, {"productId": p["id"], "quantity": item["quantity"], "unitPrice": self.money(p["price"]), "lineTotal": self.money(total)}, total

    def handle(self, method, path, body, token):
        user = self.tokens.get(token)
        if (method, path) == ("POST", "/api/auth/register"):
            if body["email"] in self.users:
                return 409, None
            self.users[body["email"]] = body
            return 201, {"id": self.new_id()}
        if (method, path) == ("POST", "/api/auth/login"):
            u = self.users.get(body["email"])
            if not u or u["password"] != body["password"]:
                return 401, None
            self.tokens[f"tok-{body['email']}"] = body["email"]
            return 200, {"token": f"tok-{body['email']}"}
        if (method, path) == ("GET", "/api/products"):
            return 200, [{**p, "price": self.money(p["price"])} for p in self.products.values()]
        if (method, path) == ("POST", "/api/cart/quote"):
            lines = [self.line(i)[1:] for i in body["items"]]
            return 200, {"lines": [l[0] for l in lines], "total": self.money(round(sum(l[1] for l in lines), 2))}
        if not user:
            return 401, None
        if (method, path) == ("POST", "/api/checkout"):
            rows = [self.line(i) for i in body["items"]]
            if any(p["stock"] < i["quantity"] for (p, _, _), i in zip(rows, body["items"])):
                return 409, None
            for (p, _, _), i in zip(rows, body["items"]):
                p["stock"] -= i["quantity"]
            o = {"id": self.new_id(), "status": "pending", "total": round(sum(r[2] for r in rows), 2), "user": user}
            self.orders[str(o["id"])] = o
            return 201, {"id": o["id"], "status": "pending", "total": self.money(o["total"])}
        if (method, path) == ("GET", "/api/orders"):
            return 200, [{"id": o["id"], "status": o["status"], "total": self.money(o["total"])} for o in self.orders.values() if o["user"] == user]
        if method == "PATCH" and path.startswith("/api/orders/") and path.endswith("/status"):
            o = self.orders.get(path.split("/")[3])
            if not o or o["user"] != user:
                return 404, None
            order = ["pending", "paid", "shipped"]
            if order.index(body["status"]) != order.index(o["status"]) + 1:
                return 409, None
            o["status"] = body["status"]
            return 200, {"id": o["id"], "status": o["status"]}
        return 404, None


def serve(shop):
    class H(BaseHTTPRequestHandler):
        def do_any(self):
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or "null") if n else None
            token = (self.headers.get("Authorization") or "").replace("Bearer ", "")
            status, out = shop.handle(self.command, self.path, body, token)
            data = json.dumps(out).encode() if out is not None else b""
            self.send_response(status); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(data))); self.end_headers()
            self.wfile.write(data)
        do_GET = do_POST = do_PATCH = do_any
        def log_message(self, *a):
            pass
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


class TestAcceptanceGate(unittest.TestCase):
    def gate(self, **kw):
        srv = serve(ReferenceShop(**kw))
        try:
            res = acceptance_check.run(f"http://127.0.0.1:{srv.server_port}")
        finally:
            srv.shutdown(); srv.server_close()
        return res, {c["case"]: c["ok"] for c in res["cases"]}

    def test_a_correct_shop_passes_every_case(self):
        res, cases = self.gate()
        self.assertEqual(res["acceptance_pct"], 100.0, [c for c in res["cases"] if not c["ok"]])
        self.assertGreaterEqual(res["total"], 25)

    def test_money_as_strings_fails_only_the_json_number_cases(self):
        res, cases = self.gate(money_as_string=True)
        failed = sorted(k for k, v in cases.items() if not v)
        self.assertEqual(failed, ["cart/quote: lines carry numeric unitPrice and lineTotal (3 T-shirt = 10 x 3 -10% = 27)",
                                  "catalog: ids are integers or UUIDs and prices are JSON numbers",
                                  "checkout: id is an integer or UUID and total is a JSON number",
                                  "orders: each order has id, status and a numeric total"])
        self.assertTrue(cases["cart/quote: 3 T-shirt = 27.00 (discount)"])  # the amounts themselves are right: one defect, four findings, no cascade

    def test_objectid_style_ids_fail_the_opaque_id_cases_but_the_rest_still_works(self):
        res, cases = self.gate(object_ids=True)
        failed = sorted(k for k, v in cases.items() if not v)
        self.assertEqual(failed, ["catalog: ids are integers or UUIDs and prices are JSON numbers",
                                  "checkout: id is an integer or UUID and total is a JSON number",
                                  "orders: each order has id, status and a numeric total"])
        self.assertTrue(cases["statuses: pending→paid→shipped in order"])  # ids are passed back untouched

    def test_helpers(self):
        self.assertTrue(all(map(acceptance_check.is_number, [1, 1.5, -2])))
        self.assertFalse(any(map(acceptance_check.is_number, ["10.00", True, None, [1]])))
        ids = [7, "0b6f2c1e-3c4d-4a5b-8c9d-0123456789ab", "507f1f77bcf86cd799439011", "7", True, None]
        self.assertEqual([acceptance_check.is_opaque_id(i) for i in ids], [True, True, False, False, False, False])

    def test_an_unreachable_server_fails_every_case_without_crashing(self):
        with mock.patch.object(acceptance_check, "call", return_value=(0, "connection refused")):  # what call() returns on a network error
            res = acceptance_check.run("http://127.0.0.1:1")
        self.assertEqual(res["passed"], 0); self.assertGreater(res["total"], 20)


COMPOSE_CONFIG = {"services": {"api": {"image": "node:22", "environment": {"PORT": "3000"}},
                               "db": {"image": "postgres:16-alpine", "environment": {"POSTGRES_USER": "shop", "POSTGRES_PASSWORD": "pw", "POSTGRES_DB": "shopdb"},
                                      "ports": [{"target": 5432, "published": "5432"}]}}}


class TestComposeHelpers(unittest.TestCase):
    def test_picks_the_postgres_service_by_image_or_by_environment(self):
        self.assertEqual(pg_runtime.pick_postgres_service(COMPOSE_CONFIG), "db")
        by_env = {"services": {"web": {"image": "nginx"}, "store": {"image": "custom/db", "environment": ["POSTGRES_PASSWORD=x"]}}}
        self.assertEqual(pg_runtime.pick_postgres_service(by_env), "store")
        self.assertIsNone(pg_runtime.pick_postgres_service({"services": {"web": {"image": "nginx"}}}))
        for img in ("postgres", "docker.io/library/postgres:15", "postgis/postgis:16-3.4", "bitnami/postgresql:16"):
            self.assertEqual(pg_runtime.pick_postgres_service({"services": {"x": {"image": img}}}), "x", img)

    def test_credentials_use_the_image_defaults_when_unset(self):
        self.assertEqual(pg_runtime.pg_credentials(COMPOSE_CONFIG["services"]["db"]), ("shop", "pw", "shopdb"))
        self.assertEqual(pg_runtime.pg_credentials({"image": "postgres"}), ("postgres", "", "postgres"))
        self.assertEqual(pg_runtime.pg_credentials({"environment": ["POSTGRES_USER=a", "POSTGRES_PASSWORD=b"]}), ("a", "b", "a"))

    def test_published_port_parsing_and_compose_file_lookup(self):
        self.assertEqual(pg_runtime.parse_published_port("0.0.0.0:49153\n[::]:49153\n"), 49153)
        self.assertIsNone(pg_runtime.parse_published_port("")); self.assertIsNone(pg_runtime.parse_published_port("no port here"))
        with tempfile.TemporaryDirectory() as t:
            self.assertIsNone(pg_runtime.find_compose(t))
            (Path(t) / "compose.yaml").write_text("services: {}", encoding="utf-8")
            self.assertEqual(pg_runtime.find_compose(t).name, "compose.yaml")
            (Path(t) / "docker-compose.yml").write_text("services: {}", encoding="utf-8")
            self.assertEqual(pg_runtime.find_compose(t).name, "docker-compose.yml")  # the documented name wins

    def test_docker_status_reports_why_it_is_unavailable(self):
        with mock.patch.object(pg_runtime.shutil, "which", return_value=None):
            cmd, why = pg_runtime.docker_status()
        self.assertIsNone(cmd); self.assertIn("not installed", why)
        with mock.patch.object(pg_runtime.shutil, "which", return_value="docker"), \
                mock.patch.object(pg_runtime.subprocess, "run", return_value=subprocess.CompletedProcess([], 1)):
            cmd, why = pg_runtime.docker_status()
        self.assertIsNone(cmd); self.assertIn("daemon is not running", why)


class FakeCompose:
    """Stands in for pg_runtime.Compose: records the calls and can fail at a step."""
    log, fail_at = [], None

    def __init__(self, cmd, file, project, log_path):
        FakeCompose.log.append(("init", project))

    def step(self, name, result):
        if name != "create_database":
            FakeCompose.log.append((name,))
        return (1, "", "failed") if FakeCompose.fail_at == name else result

    def config(self): FakeCompose.log.append(("config",)); return COMPOSE_CONFIG
    def up(self, svc): return self.step("up", (0, "", ""))
    def port(self, svc, p=5432): FakeCompose.log.append(("port",)); return 54321
    def wait_ready(self, svc, user, seconds=90): FakeCompose.log.append(("wait_ready", user)); return True
    def create_database(self, svc, user, db): FakeCompose.log.append(("create_database", db)); return self.step("create_database", (0, "", ""))
    def down(self): FakeCompose.log.append(("down",)); return 0, "", ""


class TestRunExperimentGate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name) / "project"; (self.project / "backend").mkdir(parents=True)
        self.exp = Path(self.tmp.name) / "exp"; self.exp.mkdir()
        FakeCompose.log, FakeCompose.fail_at = [], None

    def tearDown(self):
        self.tmp.cleanup()

    def gate(self, backend=None):
        backend = backend or (lambda be, env, port, expdir, wait=90: {"passed": 25, "total": 25, "acceptance_pct": 100.0, "env": env})
        with mock.patch.object(pg_runtime, "docker_status", return_value=(["docker", "compose"], None)), mock.patch.object(pg_runtime, "Compose", FakeCompose), \
                mock.patch.object(run_experiment, "run_backend_gate", backend), mock.patch.object(pg_runtime, "wait_for_port", return_value=True):
            return run_experiment.acceptance(self.project, self.exp, "claude-n1-ecommerce-r1")

    def test_skips_clearly_when_docker_is_not_available(self):
        (self.project / "docker-compose.yml").write_text("services: {}", encoding="utf-8")
        with mock.patch.object(pg_runtime, "docker_status", return_value=(None, "Docker is not installed or not on PATH")):
            self.assertEqual(run_experiment.acceptance(self.project, self.exp, "r"), {"skipped": True, "reason": "Docker is not installed or not on PATH"})

    def test_a_missing_compose_file_or_backend_is_an_error_not_a_skip(self):
        self.assertIn("docker-compose.yml not found", run_experiment.acceptance(self.project, self.exp, "r")["error"])
        self.assertIn("backend/", run_experiment.acceptance(Path(self.tmp.name) / "none", self.exp, "r")["error"])

    def test_starts_postgres_creates_the_disposable_database_runs_the_backend_and_tears_down(self):
        (self.project / "docker-compose.yml").write_text("services: {}", encoding="utf-8")
        res = self.gate()
        steps = [x[0] for x in FakeCompose.log]
        self.assertEqual(steps, ["init", "config", "up", "port", "wait_ready", "create_database", "down"])
        self.assertIn(("create_database", "eval_claude_n1_ecommerce_r1"), FakeCompose.log); self.assertIn(("init", "eval_claude_n1_ecommerce_r1"), FakeCompose.log)
        self.assertEqual(res["env"]["DATABASE_URL"], "postgresql://shop:pw@127.0.0.1:54321/eval_claude_n1_ecommerce_r1")
        self.assertTrue(res["env"]["PORT"].isdigit()); self.assertNotIn("PG_ADMIN_URL", res["env"])

    def test_teardown_happens_when_a_step_fails_or_the_backend_raises(self):
        (self.project / "docker-compose.yml").write_text("services: {}", encoding="utf-8")
        FakeCompose.fail_at = "up"
        self.assertIn("docker compose up failed", self.gate()["error"]); self.assertEqual(FakeCompose.log[-1], ("down",))
        FakeCompose.log, FakeCompose.fail_at = [], "create_database"
        self.assertIn("could not create the disposable database", self.gate()["error"]); self.assertEqual(FakeCompose.log[-1], ("down",))
        FakeCompose.log, FakeCompose.fail_at = [], None
        def boom(*a, **k):
            raise RuntimeError("npm exploded")
        self.assertEqual(self.gate(backend=boom), {"error": "npm exploded"}); self.assertEqual(FakeCompose.log[-1], ("down",))

    def test_a_compose_file_without_a_postgres_service_is_reported(self):
        (self.project / "docker-compose.yml").write_text("services: {}", encoding="utf-8")
        with mock.patch.object(FakeCompose, "config", lambda self: {"services": {"web": {"image": "nginx"}}}):
            self.assertIn("no PostgreSQL service", self.gate()["error"])


class TestRuntimesAndArtifacts(unittest.TestCase):
    def test_rubric_replaces_the_mongo_runtimes_with_postgresql_sequelize_and_pg_marked_unverified(self):
        sr = ev.RUBRIC["supported_runtimes"]
        self.assertTrue({"node", "react", "express", "postgresql", "sequelize", "pg"} <= set(sr))
        self.assertFalse({"mongoose", "mongodb"} & set(sr))
        self.assertEqual(sorted(sr["unverified"]["keys"]), ["pg", "postgresql", "sequelize"]); self.assertRegex(sr["unverified"]["date"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertEqual(sr["eol_products"]["postgresql"], "postgresql")

    def test_postgresql_support_is_read_from_endoflife_date_like_node_react_and_express(self):
        seen = []
        class Resp:
            def __init__(self, url): self.url = url
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self):
                seen.append(self.url)
                return json.dumps([{"cycle": "18", "eol": "2030-11-14"}, {"cycle": "17.1", "eol": False}, {"cycle": "13", "eol": "2025-11-13"}]).encode()
        with mock.patch("urllib.request.urlopen", lambda url, timeout=0: Resp(url)):
            r = ev.fetch_eol(False)
        self.assertEqual(sorted(r), ["express", "node", "postgresql", "react"])
        self.assertEqual(r["postgresql"], [17, 18])  # 13 is past its EOL date
        self.assertIn("https://endoflife.date/api/postgresql.json", seen)

    def test_postgres_images_are_read_from_the_compose_file(self):
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / "docker-compose.yml").write_text('services:\n  db:\n    image: postgres:14.2-alpine\n  old:\n    image: "postgres"\n  gis:\n    image: postgis/postgis:16-3.4\n  api:\n    image: node:22\n', encoding="utf-8")
            imgs = ev.postgres_images(t)
        self.assertEqual([(i["image"], i["major"]) for i in imgs], [("postgres:14.2-alpine", 14), ("postgres", None), ("postgis/postgis:16-3.4", 16)])

    def tech(self, images=(), eol=None, deps=None):
        deps = deps or {"pg": "^8.11.0", "sequelize": "^6.37.0"}
        items = [{"pkg": k, "spec": v, "latest": "9.0.0" if k == "pg" else "6.37.8", "deprecated": None} for k, v in deps.items()]
        m = {"eol": eol or {}, "postgres_images": list(images),
             "packages": {"npm": {"ok": True, "items": items}, "audit": {"ok": True, "high": 0, "critical": 0},
                          "packages": [{"dependencies": deps, "devDependencies": {}, "engines": {}}]}}
        return ev.eval_technologies(m, {}, Opts)[0]["C2"]

    def test_technologies_c2_checks_postgresql_sequelize_and_pg_against_the_table_or_endoflife(self):
        self.assertTrue(self.tech([{"file": "docker-compose.yml", "image": "postgres:16-alpine", "major": 16}])["ok"])
        bad = self.tech([{"file": "docker-compose.yml", "image": "postgres:12", "major": 12}])
        self.assertFalse(bad["ok"]); self.assertEqual(bad["value"], ["postgresql 12 (postgres:12 in docker-compose.yml)"])
        self.assertFalse(self.tech(deps={"pg": "^8.11.0", "sequelize": "^7.0.0-alpha.9"})["ok"])  # sequelize 7 is not in the (unverified) table
        self.assertFalse(self.tech(deps={"pg": "^7.18.0", "sequelize": "^6.0.0"})["ok"])
        # a supported-version list from endoflife.date replaces the table for postgresql
        self.assertFalse(self.tech([{"file": "c.yml", "image": "postgres:14", "major": 14}], eol={"postgresql": [17, 18]})["ok"])
        self.assertIn("endoflife.date", self.tech([], eol={"postgresql": [17, 18]})["desc"])
        self.assertIn("unverified since 2026-10-26", self.tech()["desc"])

    def test_an_unversioned_postgres_image_is_not_guessed(self):
        c2 = self.tech([{"file": "docker-compose.yml", "image": "postgres", "major": None}])
        self.assertTrue(c2["ok"]); self.assertEqual(c2["value"]["postgres_image_without_version_not_checked"], ["postgres in docker-compose.yml"])

    def test_er_model_is_a_complementary_declarative_artifact_that_feeds_the_data_model(self):
        a = {x["id"]: x for x in ev.RUBRIC["artifacts"]}
        self.assertEqual((a["er_model"]["level"], a["er_model"]["evidence"], a["er_model"]["feeds"]), ("complementary", "Declarative", ["data_model"]))
        self.assertEqual(a["data_schema"]["level"], "core")
        self.assertIn("Sequelize", a["data_schema"]["name"])

    def artifacts(self, er):
        m = artifact_model(er=er, schema={"tables": {"a": {}}, "sources": {"sequelize_model": 1}})
        m["artifacts"] = ev.inventory_artifacts(m, [])
        return m, {x["id"]: x for x in m["artifacts"]}

    def test_a_missing_er_file_records_the_artifact_as_absent_with_a_medium_finding(self):
        m, a = self.artifacts({"found": False, "diagram": False, "file": None, "entities": {}})
        self.assertFalse(a["er_model"]["present"]); self.assertIn("not found", a["er_model"]["detail"])
        f = {x["artifact"]: x for x in ev.artifact_findings(m)}
        self.assertEqual((f["er_model"]["severity"], f["er_model"]["affected_points"]), ("Medium", ["data_model"]))

    def test_an_er_file_without_a_diagram_is_also_absent_and_a_real_diagram_is_present(self):
        _, a = self.artifacts({"found": True, "diagram": False, "file": "docs/entity-relationship-model.md", "entities": {}})
        self.assertFalse(a["er_model"]["present"]); self.assertIn("no erDiagram", a["er_model"]["detail"])
        _, a = self.artifacts(er_from(ER_MATCH))
        self.assertTrue(a["er_model"]["present"]); self.assertIn("4 entities", a["er_model"]["detail"])

    def test_data_schema_accepts_sql_sequelize_migrations_and_sequelize_models(self):
        sources = lambda src: self.artifact_for(src)
        for src in ("sql", "sequelize_migration", "sequelize_model"):
            self.assertTrue(sources(src)["present"], src)
        self.assertFalse(self.artifact_for(None)["present"])

    def artifact_for(self, src):
        schema = {"tables": {"t": {}}, "sources": {src: 1}} if src else {"tables": {}, "sources": {}}
        return {x["id"]: x for x in ev.inventory_artifacts(artifact_model(schema=schema), [])}["data_schema"]

    def test_the_er_absence_lowers_the_confidence_of_the_data_model_point(self):
        m, _ = self.artifacts({"found": False, "diagram": False, "file": None, "entities": {}})
        m["readme"] = "# App"; m["artifacts"] = ev.inventory_artifacts(m, [])  # with a README, the ER is the only complementary gap of the data model
        m.update({"graph": {}, "packages": {}, "tests_static": {"test_cases": 1, "test_files": []}})
        stub = lambda *a: ({"C1": {"ok": True, "desc": "", "value": None, "source": "auto", "suggested": None}}, {}, [], "ok", None)
        with mock.patch.dict(ev.EVALUATORS, {"data_model": stub}, clear=True):
            pt = ev.evaluate_points(m, {}, Opts())[0]
        self.assertTrue(pt["evaluable"]); self.assertIn("er_model", pt["missing_artifacts"]); self.assertEqual(pt["confidence"], "medium")


class TestGeneratorModel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name) / "results"
        quiet = contextlib.redirect_stdout(io.StringIO())
        with quiet:
            ev.cmd_run(cls.ns("x-nomodel", model=None, allow_missing_model=True))
            ev.cmd_run(cls.ns("x-model", model="claude-sonnet-5-5"))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    @classmethod
    def ns(cls, run, **over):
        base = dict(app=str(FIX / "sequelize_app"), out=str(cls.root / run), agent="x", model="m", level="N1", domain="ecommerce", run_id=run, manual=None,
                    layers=None, test_cmd=None, run_tests=False, offline=True, accept_heuristics=False, allow_missing_model=False)
        return argparse.Namespace(**{**base, **over})

    def test_which_values_count_as_missing(self):
        self.assertTrue(all(ev.model_missing(x) for x in (None, "", "  ", "n/a", "N/A", "none", "Unknown")))
        self.assertFalse(any(ev.model_missing(x) for x in ("claude-sonnet-5-5", "gpt-5", "x")))

    def test_evaluate_refuses_to_run_without_a_model_and_says_how_to_fix_it(self):
        for missing in (None, "n/a", ""):
            with self.assertRaises(SystemExit) as cm:
                ev.cmd_run(self.ns("never", model=missing))
            self.assertIn("--model", str(cm.exception)); self.assertIn("--allow-missing-model", str(cm.exception))
        self.assertFalse((self.root / "never").exists())  # nothing was evaluated

    def test_with_the_override_the_profile_carries_a_prominent_warning(self):
        text = (self.root / "x-nomodel" / "profile.md").read_text(encoding="utf-8")
        self.assertIn("Generator model not recorded", text); self.assertIn("Model: NOT RECORDED", text)
        meta = json.loads((self.root / "x-nomodel" / "meta.json").read_text(encoding="utf-8"))
        self.assertTrue(meta["model_missing"]); self.assertIsNone(meta["model"])

    def test_with_a_model_there_is_no_warning_and_the_model_is_in_the_profile(self):
        text = (self.root / "x-model" / "profile.md").read_text(encoding="utf-8")
        self.assertNotIn("not recorded", text.lower()); self.assertIn("Model: claude-sonnet-5-5", text)
        self.assertFalse(json.loads((self.root / "x-model" / "meta.json").read_text(encoding="utf-8"))["model_missing"])

    def test_comparison_and_report_warn_only_about_the_runs_without_model(self):
        with contextlib.redirect_stdout(io.StringIO()):
            ev.cmd_aggregate(argparse.Namespace(dir=str(self.root), out=None))
        cmp_ = (self.root / "_comparison" / "comparison.md").read_text(encoding="utf-8")
        self.assertIn("Generator model not recorded** for x-nomodel.", cmp_)
        ev.record_generator_model(self.root, None)
        report = cli.write_report(self.root).read_text(encoding="utf-8")
        self.assertIn("Generator model not recorded** for x-nomodel.", report); self.assertNotIn("for x-nomodel, x-model", report)
        self.assertIn("Generator model: NOT RECORDED", report)
        self.assertIn("- " + ev.MODEL_WARNING, report)  # also in the methodological warnings
        ev.record_generator_model(self.root, "claude-sonnet-5-5")
        self.assertIn("Generator model: claude-sonnet-5-5", cli.write_report(self.root).read_text(encoding="utf-8"))

    def test_environment_json_records_the_model_and_keeps_other_keys(self):
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / "environment.json").write_text(json.dumps({"python": "3.12"}), encoding="utf-8")
            ev.record_generator_model(t, "claude-sonnet-5-5")
            env = json.loads((Path(t) / "environment.json").read_text(encoding="utf-8"))
            self.assertEqual((env["python"], env["generator_model"], env["generator_model_missing"]), ("3.12", "claude-sonnet-5-5", False))
            ev.record_generator_model(t, "n/a")
            env = json.loads((Path(t) / "environment.json").read_text(encoding="utf-8"))
            self.assertEqual((env["generator_model"], env["generator_model_missing"]), (None, True))

    def cli_args(self, **over):
        base = dict(apps=[str(FIX / "sequelize_app")], config=str(Path(self.tmp.name) / "none.json"), apps_dir=None, results=str(Path(self.tmp.name) / "cli-results"),
                    domain=None, model=None, rep=None, judge=None, judge_votes=None, judge_cmd=None, allow_same_model=None, postgres=None,
                    skip_tests=True, skip_dv8=True, offline=True, accept_heuristics=None, allow_missing_model=None)
        return argparse.Namespace(**{**base, **over})

    def test_cli_evaluate_stops_before_doing_anything_without_a_model(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = cli.cmd_evaluate(self.cli_args())
        self.assertEqual(rc, 2); self.assertIn("--model", out.getvalue()); self.assertIn("--allow-missing-model", out.getvalue())
        self.assertFalse((Path(self.tmp.name) / "cli-results").exists())

    def test_cli_options_read_the_model_and_the_override_from_the_config_file(self):
        cfg = Path(self.tmp.name) / "exp.json"
        cfg.write_text(json.dumps({"model": "claude-sonnet-5-5"}), encoding="utf-8")
        o = cli.options(self.cli_args(config=str(cfg)))
        self.assertEqual((o["model"], o["allow_missing_model"]), ("claude-sonnet-5-5", False))

    def test_run_experiment_requires_the_model_too(self):
        with mock.patch.object(sys, "argv", ["run_experiment.py", "--skip-acceptance"]):
            with self.assertRaises(SystemExit) as cm:
                run_experiment.main()
        self.assertIn("--model", str(cm.exception))


class TestSchemaInProductionCode(unittest.TestCase):
    INIT = ("const SCHEMA_SQL = `\nCREATE TABLE IF NOT EXISTS users (id SERIAL PRIMARY KEY, email TEXT NOT NULL UNIQUE);\n"
            "CREATE TABLE IF NOT EXISTS orders (id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id));\n"
            "CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id);`;\nmodule.exports = { init: (pool) => pool.query(SCHEMA_SQL) };\n")

    def test_ddl_run_by_the_backend_at_start_up_is_the_schema(self):
        with tempfile.TemporaryDirectory() as t:
            app = Path(t) / "app"; (app / "backend" / "src" / "db").mkdir(parents=True)
            (app / "backend" / "src" / "db" / "init.js").write_text(self.INIT, encoding="utf-8")
            ast = ev.run_ast(app, Path(t))
        sc = rs.extract([], ast, RUBRIC_REL)
        self.assertEqual(sorted(sc["tables"]), ["orders", "users"]); self.assertEqual(sc["sources"], {"sql": 2})
        o = sc["tables"]["orders"]
        self.assertEqual(([f["ref_table"] for f in o["foreign_keys"]], [i["columns"] for i in o["indexes"]]), (["users"], [["user_id"]]))
        self.assertTrue(o["file"].startswith("backend/src/db/init.js:"))

    def test_a_live_database_with_tables_makes_the_data_schema_artifact_present(self):
        m = artifact_model(schema={"tables": {}, "sources": {}}); m["artifacts"] = ev.inventory_artifacts(m, [])
        self.assertFalse(next(a for a in m["artifacts"] if a["id"] == "data_schema")["present"])
        m["pg"] = {"tables": {"t": {}}}
        a = next(a for a in ev.refresh_schema_artifact(m)["artifacts"] if a["id"] == "data_schema")
        self.assertTrue(a["present"]); self.assertIn("live database", a["detail"])


class TestRiskSummary(unittest.TestCase):
    def test_ranks_by_points_at_stake_and_flags_pending(self):
        pt = lambda i, subs, lvl, lo, hi: {"id": i, "name": i, "subcharacteristics": subs, "level": lvl, "level_min": lo, "level_max": hi,
                                           "pending_criteria": [] if lvl else ["C1"],
                                           "score_min": {"Fails": 0, "Partial": 0.5, "Meets": 1}[lo], "score_max": {"Fails": 0, "Partial": 0.5, "Meets": 1}[hi]}
        pts = [pt("a", ["Testability"], "Meets", "Meets", "Meets"), pt("b", ["Testability"], "Fails", "Fails", "Fails"),
               pt("c", ["Modularity"], None, "Fails", "Meets")]
        r = ev.risk_summary(pts)
        self.assertEqual([x["id"] for x in r], ["c", "b", "a"])  # worst case of c (24, sole Modularity point) beats b (15, half of Testability's 30)
        self.assertEqual((r[0]["light"], r[1]["light"], r[2]["light"]), ("⚪", "🔴", "🟢"))
        self.assertEqual((r[0]["at_stake_min"], r[0]["at_stake_max"]), (0.0, 24.0))
        self.assertEqual(r[1]["at_stake_max"], 15.0)


def artifact_model(**over):
    m = {"readme": "", "env_example": False, "contract": {"files": []}, "er": {"found": False, "diagram": False, "file": None, "entities": {}},
         "ast": {"files": [{"path": "a.js", "test": False}]}, "schema": {"tables": {"a": {}}, "sources": {"sql": 1}},
         "packages": {"packages": [{"dependencies": {}, "devDependencies": {}}]},
         "tests_static": {"test_cases": 0, "test_files": []}, "tests_run": {"executed": False}}
    m.update(over)
    return m


class TestArtifacts(unittest.TestCase):
    def levels(self, m, files=()):
        return {a["id"]: a for a in ev.inventory_artifacts(m, list(files))}

    def test_table_27_levels_and_detection(self):
        a = self.levels(artifact_model(readme="# Docs", env_example=True), ["Dockerfile", "docs/glossary.md"])
        self.assertEqual((a["source_code"]["level"], a["test_suite"]["level"], a["glossary"]["level"]), ("core", "complementary", "optional"))
        self.assertTrue(a["source_code"]["present"] and a["manifests"]["present"] and a["config_deploy"]["present"] and a["glossary"]["present"])
        self.assertFalse(a["test_suite"]["present"] or a["contract_spec"]["present"] or a["diagrams"]["present"])

    def test_missing_test_suite_is_a_high_finding_other_gaps_are_medium(self):
        m = artifact_model(); m["artifacts"] = ev.inventory_artifacts(m, [])
        f = {x["artifact"]: x["severity"] for x in ev.artifact_findings(m)}
        self.assertEqual(f["test_suite"], "High"); self.assertEqual(f["contract_spec"], "Medium")
        self.assertNotIn("glossary", f)  # optional artifacts never produce findings

    def test_missing_core_artifact_makes_the_point_not_evaluable(self):
        from unittest import mock
        m = artifact_model(schema={"tables": {}, "sources": {}}, readme="")
        m["artifacts"] = ev.inventory_artifacts(m, [])
        boom = mock.Mock(side_effect=AssertionError("must not run without its core artifact"))
        stub = lambda *a: ({"C1": {"ok": True, "desc": "", "value": None, "source": "auto", "suggested": None}}, {}, [], "ok", None)
        with mock.patch.dict(ev.EVALUATORS, {"data_model": boom, "tests": stub}, clear=True):
            pts = {p["id"]: p for p in ev.evaluate_points(m, {}, Opts())}
        dm = pts["data_model"]
        self.assertFalse(dm["evaluable"]); self.assertIsNone(dm["level"]); self.assertEqual(dm["severity"], "Not evaluable")
        self.assertEqual(dm["confidence"], "n/a"); self.assertIsNone(dm["score_min"])
        t = pts["tests"]  # no test suite: evaluated normally, but with a high-severity finding and lower confidence
        self.assertTrue(t["evaluable"]); self.assertEqual(t["severity"], "High"); self.assertEqual(t["confidence"], "medium")


def point(pid, subs, level, severity, evaluable=True):
    return {"id": pid, "name": pid, "subcharacteristics": subs, "level": level, "level_min": level, "level_max": level, "severity": severity,
            "evaluable": evaluable, "missing_artifacts": [] if evaluable else ["x"], "score_min": 1.0, "score_max": 1.0, "pending_criteria": []}


class TestDashboard(unittest.TestCase):
    def build(self, points, subs):
        prof = {"subcharacteristics": subs}
        m = {"ast": {"functions": [{"file": "a.js", "test": False, "cc": 30}, {"file": "b.js", "test": False, "cc": 2}]},
             "graph": {"modules": [], "cycles": [["a.js", "b.js"]]}, "layers": {}, "artifacts": []}
        return ev.risk_dashboard(points, prof, m)

    def test_semaphore_cutoffs_and_escalation(self):
        pts = [point("p1", ["Testability"], "Meets", "None"), point("p2", ["Modularity"], "Fails", "High")]
        subs = {"Testability": {"min": 80.0, "max": 80.0}, "Analyzability": {"min": 50.0, "max": 50.0}, "Modularity": {"min": 90.0, "max": 90.0}, "Modifiability": {"min": 10.0, "max": 10.0}}
        d = self.build(pts, subs)["semaphore"]
        self.assertEqual((d["Testability"]["state"], d["Analyzability"]["state"], d["Modifiability"]["state"]), ("green", "yellow", "red"))
        self.assertEqual(d["Modularity"]["state"], "red"); self.assertTrue(d["Modularity"]["escalated"])  # good average, forced red by a high finding

    def test_heatmap_unrelated_not_evaluable_and_escalated_cells(self):
        pts = [point("p1", ["Testability"], "Meets", "None"), point("p2", ["Modularity", "Modifiability"], None, "Not evaluable", evaluable=False),
               point("p3", ["Modularity"], "Partial", "High")]
        subs = {s: {"min": 50.0, "max": 50.0} for s in ("Testability", "Analyzability", "Modularity", "Modifiability")}
        cells = {(c["point"], c["subcharacteristic"]): c for c in self.build(pts, subs)["heatmap"]}
        self.assertEqual(cells[("p1", "Testability")]["state"], "green")
        self.assertEqual(cells[("p1", "Modularity")]["state"], "unrelated")  # not related in Table 24
        self.assertEqual(cells[("p2", "Modularity")]["state"], "not_evaluable")  # distinct from Meets
        c = cells[("p3", "Modularity")]
        self.assertEqual((c["state"], c["escalated"]), ("red", True))  # Partial but high severity

    def test_hotspots_rank_worst_files(self):
        h = self.build([], {})["hotspots"]
        self.assertEqual(h["complexity"][0]["file"], "a.js")
        self.assertEqual(sorted(x["file"] for x in h["cyclic_dependencies"]), ["a.js", "b.js"])
        self.assertEqual(h["layer_violations"], [])


class TestJudge(unittest.TestCase):
    def test_parse_extracts_json_even_with_surrounding_text(self):
        r = judge.parse('Sure: {"ok": false, "justification": "x.js:3 mixes", "confidence": "high"} end')
        self.assertEqual((r["ok"], r["confidence"]), (False, "high"))
        self.assertIsNone(judge.parse("I don't know"))
        self.assertIsNone(judge.parse('{"other": 1}'))

    def test_majority_ignores_dont_know_and_a_tie_stays_pending(self):
        v = lambda ok: {"ok": ok, "justification": "j", "confidence": "medium"}
        self.assertTrue(judge.majority([v(True), v(True), v(False)])["ok"])
        self.assertFalse(judge.majority([v(False), v(None), v(False)])["unanimous"] is False)
        self.assertIsNone(judge.majority([v(True), v(False), v(None)]))
        self.assertIsNone(judge.majority([None, v(False), v(None)]))  # a single valid vote out of three is not a majority
        self.assertFalse(judge.majority([v(False), v(False), v(None)])["ok"])
        self.assertIsNone(judge.majority([None, v(None), None]))

    def test_the_judge_only_fills_pending_and_manual_wins(self):
        jz = {"meta": {"judge_model": "j1"}, "decisions": {"cohesion": {"C3": {"ok": True, "justification": "fine"}, "C1": {"ok": False}}}}
        crits = {"C1": {"ok": True, "value": 1, "source": "auto"}, "C3": {"ok": None, "value": None, "source": "heuristic"}}
        ev.apply_manual("cohesion", crits, {"_judge": jz})
        self.assertTrue(crits["C1"]["ok"] and crits["C1"]["source"] == "auto")  # an automatic measurement is not overridden by the judge
        self.assertTrue(crits["C3"]["ok"]); self.assertEqual(crits["C3"]["source"], "judge (j1)")
        crits = {"C3": {"ok": None, "value": None, "source": "heuristic"}}
        ev.apply_manual("cohesion", crits, {"cohesion": {"C3": {"ok": False, "note": "mixes"}}, "_judge": jz})
        self.assertFalse(crits["C3"]["ok"]); self.assertEqual(crits["C3"]["source"], "manual")


class TestDV8(unittest.TestCase):
    def test_matrix_from_template(self):
        template = json.loads((ROOT / "dv8" / "matrix-template.json").read_text(encoding="utf-8"))
        graph = {"modules": [{"source": "b.js", "deps": [{"to": "a.js", "local": True}, {"to": "a.js", "local": True},
                                                          {"to": "express", "local": False}, {"to": "b.js", "local": True}]},
                             {"source": "a.js", "deps": []}]}
        matrix, dep_type = dv8_metrics.build_matrix(graph, template, "x")
        self.assertEqual(matrix["variables"], ["a.js", "b.js"]); self.assertEqual(dep_type, "Import")
        self.assertEqual(matrix["cells"], [{"src": 1, "dest": 0, "values": {"Import": 2.0}}])
        self.assertEqual(matrix["name"], "x")

    def _uih(self, classes):
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / "ast.json").write_text(json.dumps({"classes": classes}))
            return dv8_metrics.unhealthy_inheritance(Path(t))

    def test_unhealthy_inheritance(self):
        self.assertEqual(self._uih([{"name": "A", "extends": "Error"}, {"name": "B", "extends": "Error"}]), 0)
        self.assertEqual(self._uih([]), 0)
        self.assertIsNone(self._uih([{"name": "A", "extends": "Error"}, {"name": "B", "extends": "A"}]))


class TestCLI(unittest.TestCase):
    def test_identity(self):
        self.assertEqual(cli.identity("claude-n2"), ("claude", "N2"))
        self.assertEqual(cli.identity("my_app"), ("my_app", "n/a"))


if __name__ == "__main__":
    unittest.main()
