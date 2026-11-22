"""Tests of the Python reference implementation:  python -m unittest discover -s python/tests -v

They need Python and Node.js with this folder's node_modules (`npm install`); the tests that drive ESLint, Knip, Prism or StrykerJS
are skipped when the tool is not installed. None needs Docker, DV8 or PostgreSQL; one queries endoflife.date and also passes
without a network (it then checks the empty offline answer).

They cover the rules that weigh most on the results: level from criteria, layers (with doubtful classification and with no
inter-layer dependencies), coverage, duplication, the DV8 matrix and Unhealthy Inheritance, the relational schema (SQL, Sequelize
migrations and models, the ER comparison, the live catalog), the ESLint/SonarJS measures (S1192, S3776, ASCMM weaknesses), Knip and
the guard that keeps it from executing the app, the resolved versions, libyear and OSV advisories as of a reference date, the
ISO/IEC 5055 density, the weight sensitivity, the runtime contract conformance (Prism), mutation testing (StrykerJS), the acceptance
suites, the judge, the pipeline (run, rescore, aggregate) and the token records of the generator agent (token_usage.py).
"""
import argparse, contextlib, io, json, os, re, shutil, socket, subprocess, sys, tempfile, threading, time, unittest, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent  # python/
ROOT = SRC.parent  # repository root: rubric.json, tests/fixtures, js/tools
sys.path.insert(0, str(SRC))
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
import token_usage as tu  # noqa: E402


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
    """C2 comes from SonarJS S1192 itself (no-duplicate-string): a repeated literal fails it for sure; a count of 0 only passes when
    ESLint ran and parsed every file."""

    def evaluate(self, lint):
        m = {"ast": {"networkLiterals": [], "files": [{"path": "a.js", "loc": 1000, "test": False}], "envFiles": {"backend/src/config.js": 1}},
             "env_example": True}
        if lint is not None:
            m["lint"] = lint
        return ev.eval_configuration(m, {}, Opts)

    @staticmethod
    def lint(dups=(), parse_errors=()):
        return {"ok": True, "versions": {"eslint-plugin-sonarjs": "4.2.2"}, "parse_errors": list(parse_errors),
                "dup_strings": [{"file": "a.js", "line": 1, "literal": '"Server route not found"', "times": n} for n in dups]}

    def test_a_reported_literal_fails_c2(self):
        crit, met, _, finding, _ = self.evaluate(self.lint(dups=[3]))
        c = crit["C2"]
        self.assertFalse(c["ok"]); self.assertEqual(c["value"], {"Server route not found (a.js)": 3})
        self.assertEqual(c["source"], "auto (eslint-plugin-sonarjs 4.2.2)"); self.assertEqual(met["dup_per_kloc"], 2.0)

    def test_no_report_meets_c2(self):
        c = self.evaluate(self.lint())[0]["C2"]
        self.assertTrue(c["ok"]); self.assertEqual(c["value"], 0)

    def test_without_eslint_c2_is_pending(self):
        for lint in (None, {"ok": False, "error": "ESLint is not installed"}):
            crit, _, _, finding, _ = self.evaluate(lint)
            self.assertIsNone(crit["C2"]["ok"]); self.assertTrue(crit["C2"]["source"].startswith("pending (ESLint did not run"))
            self.assertIn("S1192 not measured", finding)

    def test_a_file_eslint_could_not_parse_leaves_a_zero_unproven(self):
        err = [{"file": "b.js", "line": 1, "message": "Parsing error"}]
        c = self.evaluate(self.lint(parse_errors=err))[0]["C2"]
        self.assertIsNone(c["ok"]); self.assertIn("could not parse 1 file(s): b.js", c["source"])
        self.assertFalse(self.evaluate(self.lint(dups=[4], parse_errors=err))[0]["C2"]["ok"])  # a reported literal is still certain


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
    def clones(self, base):
        with tempfile.TemporaryDirectory() as t:
            app = Path(t) / base / "app"; (app / "src").mkdir(parents=True); out = Path(t) / "out"; out.mkdir()
            body = "\n".join(f"  const v{i} = input.items.map((x) => x * {i}).filter(Boolean).reduce((a, b) => a + b, 0);" for i in range(12))
            for n in (1, 2):
                (app / "src" / f"dup{n}.js").write_text("function calc(input) {\n" + body + "\n  return v0;\n}\n")
            return ev.run_duplication(app, out)

    def test_detects_clones_and_reports_paths_relative_to_the_app(self):
        r = self.clones(".")
        self.assertTrue(r["ok"]); self.assertEqual(r["clones"], 1); self.assertGreater(r["pct"], 0)
        self.assertTrue(r["top"][0].startswith("src/dup"), r["top"])

    def test_an_app_stored_under_a_folder_the_ignore_globs_name_is_still_analyzed(self):
        # --ignore **/build/** used to match the absolute path of every file of an app stored in build/ (or tests/, dist/…)
        r = self.clones("build")
        self.assertTrue(r["ok"], r); self.assertEqual(r["clones"], 1); self.assertTrue(r["top"][0].startswith("src/dup"), r["top"])


class TestNewMeasures(unittest.TestCase):
    def test_eol_offline_returns_empty_and_online_returns_majors(self):
        self.assertEqual(ev.fetch_eol(True), {})
        r = ev.fetch_eol(False)
        for k, v in r.items():
            self.assertTrue(v and all(isinstance(x, int) for x in v), (k, v))

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
        self.assertEqual(sorted(T), ["Courses", "Enrollments", "Students", "Teachers", "desks", "rooms"])
        self.assertEqual(T["Enrollments"]["primary_key"], ["StudentId", "CourseId"])
        self.assertEqual({(f["columns"][0], f["ref_table"]) for f in T["Enrollments"]["foreign_keys"]}, {("StudentId", "Students"), ("CourseId", "Courses")})
        self.assertEqual([(f["columns"], f["ref_table"]) for f in T["Courses"]["foreign_keys"]], [(["teacherId"], "Teachers")])  # hasMany + belongsTo: one FK
        self.assertNotIn("createdAt", T["Teachers"]["columns"])  # timestamps: false
        self.assertEqual(T["Courses"]["columns"]["price"]["family"], "float")

    def test_model_options_held_in_a_const_and_spread_are_read(self):
        T = self.m["tables"]  # `define('rooms', attrs, frozen)` with `const frozen = { timestamps: false, freezeTableName: true }`
        self.assertNotIn("roomses", T); self.assertNotIn("createdAt", T["rooms"]["columns"])
        self.assertIn("createdAt", T["desks"]["columns"])  # `{ ...frozen, timestamps: true }`: the later key wins, the name stays frozen

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

    def test_every_mermaid_cardinality_token_is_accepted_on_either_side(self):
        er = ra.parse_er("```mermaid\nerDiagram\n    users o|--o{ coupons : deleted_by\n    orders }|..|{ tags : t\n```")
        self.assertEqual([(r["left"], r["left_card"], r["right"], r["right_card"]) for r in er["relationships"]],
                         [("users", "o|", "coupons", "o{"), ("orders", "}|", "tags", "|{")])

    def test_alter_in_a_sql_file_applies_to_a_table_created_by_the_startup_ddl(self):
        # db.js creates the base tables in a string it runs at start-up and then reads migrations/r2.sql, which alters them
        ast = {"sqlStrings": [{"file": "backend/src/db.js", "line": 30, "migration": False,
                               "text": "CREATE TABLE IF NOT EXISTS users (id SERIAL PRIMARY KEY, email TEXT NOT NULL)"}]}
        s = rs.extract([("backend/src/migrations/r2.sql", "ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(10) NOT NULL;\n"
                                                          "CREATE INDEX users_role ON users(role);\nALTER TABLE ghosts ADD COLUMN x int;")],
                       ast, RUBRIC_REL)
        self.assertIn("role", s["tables"]["users"]["columns"]); self.assertEqual([i["columns"] for i in s["tables"]["users"]["indexes"]], [["role"]])
        self.assertEqual([u for u in s["unparsed"] if "not created before" in u],
                         ["ALTER TABLE on a table not created before: ghosts (backend/src/migrations/r2.sql)"])  # still reported

    def test_er_that_documents_an_ignored_migration_table_still_matches(self):
        # schema_migrations is in relational.ignore_tables: the schema drops it, so the ER side must drop it too (and its lines)
        er = ER_MATCH.replace("erDiagram", "erDiagram\n    schema_migrations {\n        varchar version PK\n    }\n"
                                           "    schema_migrations ||--o{ ORDERS : tracks", 1)
        self.assertIn("schema_migrations", ra.parse_er(er)["entities"])
        c = ra.compare_er(er_from(er), dm_model(OK_SQL)["schema"], RUBRIC_REL)
        self.assertTrue(c["matches"], c); self.assertEqual(c["entities_not_in_schema"], []); self.assertEqual(c["relationships_not_in_schema"], [])

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
        p = subprocess.run(["node", "-e", code], cwd=ROOT / "js" / "tools", capture_output=True, text=True, timeout=60)
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
            p = subprocess.run(["node", "pg_schema.js", cmd, "production"], cwd=ROOT / "js" / "tools", capture_output=True, text=True, timeout=60,
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
        def exercise(be, env, port, res, wait, skip_seed, log, domain="ecommerce", gate=True):
            seen["env"], seen["domain"], seen["gate"] = env, domain, gate
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
        backend = backend or (lambda be, env, port, expdir, wait=90, domain="ecommerce": {"passed": 25, "total": 25, "acceptance_pct": 100.0, "env": env})
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
        self.assertEqual((f["er_model"]["severity"], f["er_model"]["affected_points"]), ("Marginal", ["data_model"]))

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
                    skip_tests=True, skip_dv8=True, offline=True, accept_heuristics=None, allow_missing_model=None, usage_dir=None)
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


class TestLayerNames(unittest.TestCase):
    def layers(self, paths):
        ast = {"files": [{"path": p, "test": False, "frontend": False} for p in paths]}
        return ev.classify_layers(ast, ".", None)[0]

    def test_pern_directory_names(self):
        L = self.layers(["backend/src/http/validation/schemas.js", "backend/src/http/routes.js", "backend/src/data/Migrator.js",
                         "backend/src/data/repositories/SequelizeOrderRepository.js", "backend/src/security/hasher.js", "backend/src/services/CartService.js"])
        self.assertEqual(L["backend/src/http/validation/schemas.js"], "presentation")  # validation schemas are not the data layer
        self.assertEqual((L["backend/src/http/routes.js"], L["backend/src/data/Migrator.js"], L["backend/src/security/hasher.js"]), ("presentation", "data", "shared"))
        self.assertEqual((L["backend/src/data/repositories/SequelizeOrderRepository.js"], L["backend/src/services/CartService.js"]), ("data", "business"))

    def test_schemas_outside_http_is_shared_not_data(self):
        self.assertEqual(self.layers(["backend/src/schemas/order.js"])["backend/src/schemas/order.js"], "shared")


class TestSqlInjectionIndicator(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as t:
            app = Path(t) / "app"; (app / "backend").mkdir(parents=True)
            (app / "backend" / "repo.js").write_text(
                "const COLS = 'id, name';\nlet dynamicCols = process.env.COLS;\n"
                "async function a(db, lock) { return db.query(`SELECT ${COLS} FROM t ${lock ? 'FOR UPDATE' : ''}`); }\n"   # constants: safe
                "async function b(db, order) { return db.query(`SELECT * FROM t ORDER BY ${order}`); }\n"                    # parameter: injectable
                "async function c(db, id) { return db.query('SELECT * FROM t WHERE id = ' + id); }\n"                         # concatenation: injectable
                "async function d(db) { return db.query(`SELECT ${dynamicCols} FROM t`); }\n"                                  # `let`: not a constant
                "async function e(db, id) { return db.query('SELECT * FROM t WHERE id = $1', [id]); }\n", encoding="utf-8")
            cls.ast = ev.run_ast(app, Path(t))

    def test_only_non_constant_interpolation_is_flagged(self):
        lines = sorted(x["line"] for x in self.ast["security"]["sqlInjection"])
        self.assertEqual(lines, [4, 5, 6])


class TestJudgeEvidence(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name); self.res = t / "res"; self.res.mkdir(); (t / "app" / "src").mkdir(parents=True)
        (self.res / "metrics.json").write_text("{}", encoding="utf-8")
        for name, body in (("compositionRoot.js", "wire(new Repo(), new Service())"), ("ctrl.js", "controller code"), ("svc.js", "service code"), ("repo.js", "repo code")):
            (t / "app" / "src" / name).write_text(body, encoding="utf-8")
        files = [{"path": f"src/{n}", "test": False, "frontend": False, "loc": 1} for n in ("compositionRoot.js", "ctrl.js", "svc.js", "repo.js")]
        self.m = {"app": str(t / "app"), "ast": {"files": files, "queryFields": [], "routes": []}, "readme": "Prices are copied into order lines as a snapshot.",
                  "schema": {"tables": {}}, "er": {"found": True, "file": "docs/entity-relationship-model.md", "text": "erDiagram\n  USERS { int id PK }"}}
        (self.res / "detected_layers.json").write_text(json.dumps({"src/ctrl.js": {"layer": "presentation"}, "src/svc.js": {"layer": "business"},
                                                                    "src/repo.js": {"layer": "data"}}), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_data_model_evidence_includes_the_er_document_and_the_readme(self):
        text = judge.evidence("data_model", "C2", self.res, self.m, {"finding": "f", "evidence": []})
        self.assertIn("erDiagram", text); self.assertIn("snapshot", text)
        self.m["er"] = {"found": False, "text": ""}
        self.assertIn("delivers no ER document", judge.evidence("data_model", "C2", self.res, self.m, {"finding": "f", "evidence": []}))

    def test_layers_evidence_shows_the_wiring_and_one_file_per_layer_when_there_are_no_dependencies(self):
        text = judge.evidence("layers", "C2", self.res, self.m, {"finding": "0 inter-layer dependencies", "evidence": []})
        for needle in ("wire(new Repo()", "controller code", "service code", "repo code"):
            self.assertIn(needle, text)


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

    def test_a_mermaid_diagram_in_docs_counts_as_an_architecture_diagram_but_an_er_diagram_does_not(self):
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / "docs" / "R2").mkdir(parents=True)
            (Path(t) / "docs" / "R2" / "architecture.md").write_text("# A\n\n```mermaid\nflowchart TD\n  A --> B\n```\n", encoding="utf-8")
            (Path(t) / "docs" / "entity-relationship-model.md").write_text("```mermaid\n%% schema\nerDiagram\n  a ||--o{ b : x\n```\n", encoding="utf-8")
            files = ["docs/R2/architecture.md", "docs/entity-relationship-model.md"]
            d = self.levels(artifact_model(app=t), files)["diagrams"]
            self.assertTrue(d["present"]); self.assertEqual(d["detail"], "docs/R2/architecture.md (embedded diagram)")
            self.assertFalse(self.levels(artifact_model(app=t), files[1:])["diagrams"]["present"])

    def test_table_27_levels_and_detection(self):
        a = self.levels(artifact_model(readme="# Docs", env_example=True), ["Dockerfile", "docs/glossary.md"])
        self.assertEqual((a["source_code"]["level"], a["test_suite"]["level"], a["glossary"]["level"]), ("core", "complementary", "optional"))
        self.assertTrue(a["source_code"]["present"] and a["manifests"]["present"] and a["config_deploy"]["present"] and a["glossary"]["present"])
        self.assertFalse(a["test_suite"]["present"] or a["contract_spec"]["present"] or a["diagrams"]["present"])

    def test_missing_test_suite_is_a_critical_finding_other_gaps_are_marginal(self):
        m = artifact_model(); m["artifacts"] = ev.inventory_artifacts(m, [])
        f = {x["artifact"]: x["severity"] for x in ev.artifact_findings(m)}
        self.assertEqual(f["test_suite"], "Critical"); self.assertEqual(f["contract_spec"], "Marginal")
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
        t = pts["tests"]  # no test suite: evaluated normally, but with a Critical finding (IEEE 1028, 6.8.3) and lower confidence
        self.assertTrue(t["evaluable"]); self.assertEqual(t["severity"], "Critical"); self.assertEqual(t["confidence"], "medium")


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
        pts = [point("p1", ["Testability"], "Meets", "Negligible"), point("p2", ["Modularity"], "Fails", "Critical")]
        subs = {"Testability": {"min": 80.0, "max": 80.0}, "Analyzability": {"min": 50.0, "max": 50.0}, "Modularity": {"min": 90.0, "max": 90.0}, "Modifiability": {"min": 10.0, "max": 10.0}}
        d = self.build(pts, subs)["semaphore"]
        self.assertEqual((d["Testability"]["state"], d["Analyzability"]["state"], d["Modifiability"]["state"]), ("green", "yellow", "red"))
        self.assertEqual(d["Modularity"]["state"], "red"); self.assertTrue(d["Modularity"]["escalated"])  # good average, forced red by a high finding

    def test_heatmap_unrelated_not_evaluable_and_escalated_cells(self):
        pts = [point("p1", ["Testability"], "Meets", "Negligible"), point("p2", ["Modularity", "Modifiability"], None, "Not evaluable", evaluable=False),
               point("p3", ["Modularity"], "Partial", "Critical")]
        subs = {s: {"min": 50.0, "max": 50.0} for s in ("Testability", "Analyzability", "Modularity", "Modifiability")}
        cells = {(c["point"], c["subcharacteristic"]): c for c in self.build(pts, subs)["heatmap"]}
        self.assertEqual(cells[("p1", "Testability")]["state"], "green")
        self.assertEqual(cells[("p1", "Modularity")]["state"], "unrelated")  # not related in Table 24
        self.assertEqual(cells[("p2", "Modularity")]["state"], "not_evaluable")  # distinct from Meets
        c = cells[("p3", "Modularity")]
        self.assertEqual((c["state"], c["escalated"]), ("red", True))  # Partial but Critical severity

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
        template = json.loads((ROOT / "js" / "tools" / "dv8" / "matrix-template.json").read_text(encoding="utf-8"))
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
        self.assertEqual(cli.identity("claude-n2"), ("claude", "N2", None))
        self.assertEqual(cli.identity("my_app"), ("my_app", "n/a", None))

    def test_identity_reads_the_domain_from_the_name(self):
        self.assertEqual(cli.identity("claude-cinema-n1"), ("claude", "N1", "cinema"))
        self.assertEqual(cli.identity("Codex-Ecommerce-N3"), ("codex", "N3", "ecommerce"))
        self.assertEqual(cli.identity("my-app-n1"), ("my-app-n1", "n/a", None))  # "app" is not a domain with requirements
        self.assertIn("cinema", cli.known_domains()); self.assertIn("ecommerce", cli.known_domains())

    def test_execute_turns_a_timeout_into_a_return_code(self):
        rc, out = cli.execute([sys.executable, "-c", "import time; time.sleep(5)"], timeout=1)
        self.assertEqual(rc, cli.TIMEOUT_RC); self.assertIn("TIMEOUT", out)


if __name__ == "__main__":
    unittest.main()


class TestIso5055ScoredCriteria(unittest.TestCase):
    """CWE-1080, CWE-561 and CWE-1041: weaknesses of the ISO/IEC 5055 maintainability measure that now change a level."""

    def cohesion(self, files):
        fns = [{"file": "a.js", "line": 1, "name": "f", "fanout": 0, "test": False}]
        m = {"ast": {"functions": fns, "files": files, "classes": []}, "graph": {"modules": [], "cycles": []}}
        return ev.eval_cohesion(m, {"dv8": {"DL": 0.9}}, Opts)[0]

    def test_cwe1080_file_above_the_threshold_fails_c4(self):
        c = self.cohesion([{"path": "big.js", "loc": 1001, "test": False}])
        self.assertFalse(c["C4"]["ok"]); self.assertEqual(c["C4"]["value"], 1)

    def test_cwe1080_file_at_the_threshold_passes(self):
        self.assertTrue(self.cohesion([{"path": "ok.js", "loc": 1000, "test": False}])["C4"]["ok"])

    def test_cwe1080_ignores_test_files(self):
        self.assertTrue(self.cohesion([{"path": "big.test.js", "loc": 5000, "test": True}])["C4"]["ok"])

    @staticmethod
    def knip(**over):
        return {"ok": True, "version": "6.44.1", "files": [], "dependencies": [], "devDependencies": [], "binaries": [], "unlisted": [],
                "unresolved": [], "exports": [], "config_load_errors": [], **over}

    def coupling(self, files, knip=None, dev=False):
        m = {"ast": {"files": files, "functions": [], "classes": []},
             "graph": {"modules": [{"source": "index.js", "deps": []}], "cycles": []}, "packages": {"direct": 4}}
        if knip is not None:
            m["knip"] = knip
        with mock.patch.dict(ev.RUBRIC["thresholds"]["coupling"], {"include_devdependencies": dev}):
            return ev.eval_coupling(m, {"dv8": {"PC": 0.1}}, Opts)[0]

    def test_cwe561_a_file_knip_cannot_reach_fails_c5(self):
        files = [{"path": "index.js", "test": False}, {"path": "orphan.js", "test": False}, {"path": "old.test.js", "test": True}]
        c = self.coupling(files, self.knip(files=["orphan.js", "old.test.js", "dist/bundle.js"]))  # only production files analyzed count
        self.assertFalse(c["C5"]["ok"]); self.assertEqual(c["C5"]["value"], 1); self.assertEqual(c["C5"]["source"], "auto (Knip 6.44.1)")
        self.assertTrue(self.coupling(files, self.knip())["C5"]["ok"])

    def test_unused_dependencies_and_the_binaries_of_dev_dependencies(self):
        k = self.knip(dependencies=["backend:lodash"], devDependencies=["backend:jest", "backend:nodemon"], binaries=["backend:jest"])
        self.assertEqual(self.coupling([], k)["C4"]["value"], "1/4 = 25.0%")
        self.assertEqual(self.coupling([], k, dev=True)["C4"]["value"], "2/4 = 50.0%")  # jest runs as a binary: used

    def test_without_knip_c4_and_c5_are_pending(self):
        for k in (None, {"ok": False, "error": "Knip is not installed"}):
            c = self.coupling([{"path": "orphan.js", "test": False}], k)
            self.assertEqual((c["C4"]["ok"], c["C5"]["ok"]), (None, None)); self.assertTrue(c["C5"]["source"].startswith("pending (Knip did not run"))

    def test_mmo_1_g_no_longer_counts_cycles_twice(self):
        """A cycle must lower C1 only: counting it in the C2 numerator let one defect lower two criteria."""
        mods = [{"source": "a.js", "deps": [{"to": "b.js", "module": "b.js", "local": True}]},
                {"source": "b.js", "deps": [{"to": "a.js", "module": "a.js", "local": True}]}]
        m = {"ast": {"files": [{"path": "a.js", "test": False}, {"path": "b.js", "test": False}], "functions": [], "classes": []},
             "graph": {"modules": mods, "cycles": [["a.js", "b.js"]]},
             "packages": {"direct": 4}}
        c = ev.eval_coupling(m, {"dv8": {"PC": 0.1}}, Opts)[0]
        self.assertFalse(c["C1"]["ok"])   # the cycle is reported here
        self.assertTrue(c["C2"]["ok"])    # and no longer penalised again here
        self.assertEqual(c["C2"]["value"], 1.0)

    def cyclomatic(self, dup=None, cc=1):
        fns = [{"file": "a.js", "line": 1, "name": "f", "cc": cc, "test": False}]
        m = {"ast": {"functions": fns}}
        if dup is not None:
            m["duplication"] = {"ok": True, "pct": dup, "clones": 1, "top": ["src/a.js"]}
        return ev.eval_cyclomatic(m, {}, Opts)

    def test_cwe1041_duplication_within_the_threshold_keeps_meets(self):
        crits, _, _, _, level = self.cyclomatic(dup=10.0)
        self.assertTrue(crits["C3"]["ok"]); self.assertEqual(level[0], "Meets")

    def test_cwe1041_duplication_above_the_threshold_lowers_the_level(self):
        crits, _, _, _, level = self.cyclomatic(dup=20.0)
        self.assertFalse(crits["C3"]["ok"]); self.assertEqual(level[0], "Partial")

    def test_cwe1041_pending_when_jscpd_did_not_run_gives_a_range(self):
        crits, _, _, _, level = self.cyclomatic(dup=None)
        self.assertIsNone(crits["C3"]["ok"]); self.assertEqual(crits["C3"]["source"], "pending (jscpd)")
        self.assertEqual((level[0], level[1], level[2]), (None, "Partial", "Meets"))

    def test_complexity_leveling_is_preserved_when_duplication_is_fine(self):
        self.assertEqual(self.cyclomatic(dup=1.0, cc=1)[4][0], "Meets")       # X = 1.00
        self.assertEqual(self.cyclomatic(dup=1.0, cc=99)[4][0], "Fails")      # X = 0.00


class TestBackingTraceability(unittest.TestCase):
    """Every threshold and weight must declare its source: it is what the thesis cites."""

    VALID = {"normative_exact", "normative_alternate", "normative_zero_count", "function_only", "tool_parameter", "own_calibration"}

    def test_every_threshold_declares_a_backing(self):
        missing = [f"thresholds.{p}.{k}" for p, vals in ev.RUBRIC["thresholds"].items() for k in vals
                   if not k.startswith("_") and f"thresholds.{p}.{k}" not in ev.RUBRIC["backing"]]
        self.assertEqual(missing, [], f"without backing: {missing}")

    def test_top_level_weights_and_scales_declare_a_backing(self):
        for key in ("subcharacteristic_weights", "point_weights", "partial_min_fraction", "level_score", "level_severity",
                    "risk_dashboard.semaphore", "risk_dashboard.hotspots_top_n", "supported_runtimes"):
            self.assertIn(key, ev.RUBRIC["backing"])

    def test_every_backing_entry_has_a_known_type_and_a_locator_when_normative(self):
        for key, b in ev.RUBRIC["backing"].items():
            if key.startswith("_"):
                continue
            self.assertIn(b["type"], self.VALID, key)
            if b["type"].startswith("normative") or b["type"] == "function_only":
                self.assertTrue(b.get("standard") and b.get("locator"), f"{key} claims {b['type']} without a standard and locator")

    def test_normative_exact_entries_match_the_value_in_the_rubric(self):
        for path, default in (("thresholds.cyclomatic.function_threshold", 20), ("thresholds.cohesion.fanout_max", 5),
                              ("thresholds.cohesion.file_loc_max", 1000), ("thresholds.hierarchies.depth_max", 7),
                              ("thresholds.hierarchies.children_max", 10), ("thresholds.dead_code.structural_max_files", 0)):
            group, key = path.split(".")[1], path.split(".")[2]
            b = ev.RUBRIC["backing"][path]
            self.assertEqual(b["type"], "normative_exact", path)
            self.assertEqual(b["standard_default"], default, path)
            self.assertEqual(ev.RUBRIC["thresholds"][group][key], default, f"{path} drifted from the ISO/IEC 5055 default")

    def test_ascmm_coverage_adds_up(self):
        c = ev.RUBRIC["backing"]["_coverage_ascmm"]
        self.assertEqual(c["total_weaknesses"] - len(c["not_applicable_to_js_ts"]), c["applicable"])
        self.assertEqual(len(c["scored"]) + len(c["informational"]) + len(c["not_detected"]), c["applicable"])


class TestTokenUsage(unittest.TestCase):
    """token_usage.py: parsing of each agent's usage records, normalization, recording per phase and its place in the report."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.d = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, objs):
        p = self.d / name
        p.write_text("".join(json.dumps(o) + "\n" for o in objs), encoding="utf-8")
        return p

    @staticmethod
    def claude_msg(mid, inp, cw, cr, out, think=0):
        return {"type": "assistant", "sessionId": "s1", "timestamp": "2026-11-07T17:00:00Z",
                "message": {"id": mid, "model": "claude-sonnet-5-5", "role": "assistant",
                            "usage": {"input_tokens": inp, "cache_creation_input_tokens": cw, "cache_read_input_tokens": cr,
                                      "output_tokens": out, "output_tokens_details": {"thinking_tokens": think}}}}

    @staticmethod
    def manual(i, o):
        return {**tu.finish({**tu.empty(), "input_tokens": i, "output_tokens": o, "requests": 1}), "format": "manual", "file": None, "session_id": None}

    def test_claude_transcript_is_deduplicated_by_message_id_and_input_includes_the_cache(self):
        user = {"type": "user", "message": {"role": "user", "content": "Your working folder is apps/claude-cinema-n1. Read PROMPT.md"}}
        p = self.write("s.jsonl", [user, self.claude_msg("m1", 2, 100, 1000, 50, 10), self.claude_msg("m1", 2, 100, 1000, 50, 10),
                                   self.claude_msg("m2", 3, 0, 1100, 20)])
        s = tu.parse_file(p)
        self.assertEqual(s["format"], "claude-transcript")
        self.assertEqual((s["input_tokens"], s["cache_read_tokens"], s["cache_write_tokens"]), (2205, 2100, 100))
        self.assertEqual((s["output_tokens"], s["reasoning_tokens"], s["total_tokens"], s["requests"]), (70, 10, 2275, 2))
        self.assertEqual(s["models"], ["claude-sonnet-5-5"])
        self.assertEqual(tu.guess(s, ["claude-cinema-n1", "claude-cinema-n2"])[:2], ("claude-cinema-n1", "initial"))

    def test_claude_result_json_adds_every_model(self):
        p = self.d / "agent.log"
        p.write_text(json.dumps({"type": "result", "session_id": "x", "num_turns": 7, "total_cost_usd": 1.5, "modelUsage": {
            "claude-sonnet-5-5": {"inputTokens": 10, "outputTokens": 100, "cacheReadInputTokens": 1000, "cacheCreationInputTokens": 50},
            "claude-haiku-5-5": {"inputTokens": 5, "outputTokens": 10, "cacheReadInputTokens": 0, "cacheCreationInputTokens": 0}}}), encoding="utf-8")
        s = tu.parse_file(p)
        self.assertEqual((s["format"], s["input_tokens"], s["output_tokens"], s["total_tokens"], s["cost_usd"]), ("claude-result", 1065, 110, 1175, 1.5))

    def test_codex_rollout_uses_the_last_cumulative_count_and_exec_json_adds_the_turns(self):
        def tc(i, c, o):
            return {"type": "event_msg", "payload": {"type": "token_count", "info": {"total_token_usage": {
                "input_tokens": i, "cached_input_tokens": c, "output_tokens": o, "reasoning_output_tokens": 3, "total_tokens": i + o}}}}
        r = self.write("rollout-x.jsonl", [{"type": "session_meta", "payload": {"id": "t1", "parent_thread_id": "p"}},
                                           tc(100, 80, 10), {"type": "event_msg", "payload": {"type": "token_count", "info": None}}, tc(300, 250, 40)])
        s = tu.parse_file(r)
        self.assertEqual((s["format"], s["input_tokens"], s["cache_read_tokens"], s["output_tokens"], s["total_tokens"], s["subagent"]),
                         ("codex-rollout", 300, 250, 40, 340, True))
        e = self.write("exec.jsonl", [{"type": "thread.started", "thread_id": "t2"},
                                      {"type": "turn.completed", "usage": {"input_tokens": 100, "cached_input_tokens": 50, "output_tokens": 5}},
                                      {"type": "turn.completed", "usage": {"input_tokens": 200, "cached_input_tokens": 150, "output_tokens": 7}}])
        s = tu.parse_file(e)
        self.assertEqual((s["format"], s["input_tokens"], s["cache_read_tokens"], s["total_tokens"], s["requests"]), ("codex-exec", 300, 200, 312, 2))

    def test_a_file_without_usage_is_rejected(self):
        with self.assertRaises(ValueError):
            tu.parse_file(self.write("x.jsonl", [{"type": "user", "message": {"content": "hi"}}]))

    def test_an_orchestrator_that_names_the_app_only_inside_the_transcript_is_not_attributed(self):
        s = {"file": str(self.write("o.jsonl", [{"x": "apps/claude-n1 apps/claude-n1 apps/claude-n1"}])), "prompt": "evaluate everything", "subagent": False}
        self.assertIsNone(tu.guess(s, ["claude-n1", "claude-n2"])[0])
        self.assertEqual(tu.guess({**s, "subagent": True}, ["claude-n1", "claude-n2"])[0], "claude-n1")
        self.assertEqual(tu.guess({"prompt": "Apply r2-additional-requirements.md in apps/claude-n1"}, ["claude-n1"])[:2], ("claude-n1", "r2"))

    def test_phases_are_recorded_separately_and_the_ratio_compares_r2_with_initial(self):
        path = self.d / "usage" / "claude-n1.json"
        tu.record_phase(path, "claude-n1", "initial", [self.manual(1000, 100)])
        tu.record_phase(path, "claude-n1", "r2", [self.manual(400, 40)])
        tu.record_phase(path, "claude-n1", "r2", [self.manual(100, 10)], append=True)
        data = tu.load(path)
        self.assertEqual(list(data["phases"]), ["initial", "r2"])
        self.assertEqual(data["phases"]["r2"]["totals"]["total_tokens"], 550)
        self.assertEqual(tu.summary(data)["r2_vs_initial"]["total_tokens"], 0.5)
        with self.assertRaises(ValueError):
            tu.record_phase(path, "claude-n1", "second", [self.manual(1, 1)])

    def test_the_report_and_the_comparison_read_the_copy_in_results(self):
        usage = self.d / "usage"
        tu.record_phase(usage / "claude-n1.json", "claude-n1", "initial", [self.manual(1000, 100)])
        tu.record_phase(usage / "claude-n1.json", "claude-n1", "r2", [self.manual(500, 50)])
        run = self.d / "results" / "claude-n1-ecommerce-r1"
        self.assertIsNone(cli.copy_token_usage(Path("apps/claude-n1"), run, str(usage)))
        cols = ev.token_columns(run)
        self.assertEqual((cols["tokens_initial_total"], cols["tokens_r2_total"], cols["tokens_r2_vs_initial"]), (1100, 550, 0.5))
        section = "\n".join(cli.token_section([(run, {"meta": {"run_id": run.name}}, [])]))
        self.assertIn("| claude-n1-ecommerce-r1 | 1.0 k | 100 | **1.1 k** | 500 | 50 | **550** | ×0.50 | 1.6 k |", section)
        self.assertIn("not recorded", cli.copy_token_usage(Path("apps/claude-n2"), run, str(usage)))
        self.assertFalse((run / tu.RESULT_FILE).exists())  # a stale copy does not survive once the record is gone
        self.assertIn("Not recorded", "\n".join(cli.token_section([(run, {"meta": {"run_id": run.name}}, [])])))
        self.assertIsNone(ev.token_columns(run)["tokens_initial_total"])

    def test_scan_attributes_a_session_by_the_app_folder_it_ran_in(self):
        apps = ["codex-ecommerce-n1", "codex-ecommerce-n2"]
        s = {"cwd": r"C:\exp\apps\codex-ecommerce-n2", "prompt": "Apply the additional requirements defined in `r2-additional-requirements.md`",
             "file": "", "subagent": False}  # a `codex exec` launched by an orchestrator: not a subagent, and its prompt names no app
        self.assertEqual(tu.guess(s, apps), ("codex-ecommerce-n2", "r2", ["codex-ecommerce-n2"]))
        orchestrator = {**s, "cwd": r"C:\exp", "prompt": "For each application codex-ecommerce-n1 and codex-ecommerce-n2 …"}
        self.assertIsNone(tu.guess(orchestrator, apps)[0])

    def test_the_individual_profile_shows_the_tokens_of_each_phase(self):
        from evaluator.outputs import token_markdown
        run = self.d / "results" / "claude-n1-ecommerce-r1"; run.mkdir(parents=True)
        self.assertIn("No token record", "\n".join(token_markdown(run)))
        tu.record_phase(run / tu.RESULT_FILE, "claude-n1", "initial", [self.manual(1000, 100)])
        md = "\n".join(token_markdown(run))
        self.assertIn("| Initial | 1.0 k | 100 | **1.1 k** |", md); self.assertIn("| R2 | — | — | **missing** | — |", md)
        tu.record_phase(run / tu.RESULT_FILE, "claude-n1", "r2", [self.manual(500, 50)])
        md = "\n".join(token_markdown(run))
        self.assertIn("| R2 | 500 | 50 | **550** |", md); self.assertIn("**×0.50**", md)

    def test_run_experiment_prompts_name_the_domain_and_the_r2_inputs(self):
        prompt = run_experiment.build_prompt("N2", "cinema")
        self.assertIn("technical-n2.md", prompt); self.assertIn("requirements-cinema.md", prompt); self.assertNotIn("{", prompt)
        project = self.d / "p"
        run_experiment.prepare_phase("initial", "N1", "cinema", project)
        self.assertTrue((project / "PROMPT.md").exists() and (project / "requirements-cinema.md").exists())
        with self.assertRaises(SystemExit):
            run_experiment.prepare_phase("r2", "N1", "cinema", project)  # no backend/ yet
        (project / "backend").mkdir()
        r2 = run_experiment.prepare_phase("r2", "N1", "cinema", project)
        self.assertIn("r2-additional-requirements.md", r2); self.assertTrue((project / "r2-additional-requirements.md").exists())
        self.assertEqual((project / "PROMPT-R2.md").read_text(encoding="utf-8"), r2)


import datetime as _dt, re, shutil  # noqa: E402
import pg_seed  # noqa: E402


class ReferenceCinema:
    """In-memory implementation of the minimum HTTP interface of requirements-cinema.md, used to test the cinema gate.
    Screenings are tomorrow at the seed times (local time) and are returned in UTC with a Z, as JavaScript's toISOString does.
    `money_as_string` returns prices as strings; `no_locks` ignores other users' locks."""
    def __init__(self, money_as_string=False, no_locks=False):
        self.money_as_string, self.no_locks = money_as_string, no_locks
        self.users, self.tokens, self.orders, self.locks, self.sold = {}, {}, [], {}, set()
        self.movies = [{"id": 1, "title": "Movie One", "description": "d", "imageUrl": "u"},
                       {"id": 2, "title": "Movie Two", "description": "d", "imageUrl": "u"}]
        tomorrow = _dt.date.today() + _dt.timedelta(days=1)
        self.showtimes = []
        for i, (movie, room, hm) in enumerate(((1, 1, "14:00"), (1, 1, "20:00"), (2, 2, "16:30"), (2, 2, "21:00")), start=1):
            local = _dt.datetime.combine(tomorrow, _dt.time(*map(int, hm.split(":")))).astimezone()
            self.showtimes.append({"id": i, "movieId": movie, "room": room, "hm": hm,
                                   "startsAt": local.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")})
        self.seats = {st["id"]: [{"id": st["id"] * 100 + k, "label": f"{r}{n}"} for k, (r, n) in enumerate(((r, n) for r in "ABCD" for n in range(1, 6)))]
                      for st in self.showtimes}

    def price(self, st):
        return 9.0 if st["hm"] >= "17:00" else 6.0

    def money(self, x):
        return f"{x:.2f}" if self.money_as_string else x

    def status(self, st_id, seat_id, user=None):
        if (st_id, seat_id) in self.sold:
            return "sold"
        lk = self.locks.get((st_id, seat_id))
        return "locked" if lk and lk != user else ("locked" if lk else "available")

    def handle(self, method, path, body, token):
        user = self.tokens.get(token)
        if (method, path) == ("POST", "/api/auth/register"):
            if body["email"] in self.users:
                return 409, None
            self.users[body["email"]] = body
            return 201, {"id": len(self.users)}
        if (method, path) == ("POST", "/api/auth/login"):
            u = self.users.get(body["email"])
            if not u or u["password"] != body["password"]:
                return 401, None
            self.tokens[f"tok-{body['email']}"] = body["email"]
            return 200, {"token": f"tok-{body['email']}"}
        if (method, path) == ("GET", "/api/movies"):
            return 200, self.movies
        if (method, path) == ("GET", "/api/showtimes"):
            return 200, [{k: st[k] for k in ("id", "movieId", "startsAt", "room")} | {"price": self.money(self.price(st))} for st in self.showtimes]
        parts = path.strip("/").split("/")
        st = next((s for s in self.showtimes if len(parts) > 2 and str(s["id"]) == parts[2]), None)
        if method == "GET" and len(parts) == 4 and parts[3] == "seats" and st:
            return 200, [{"id": s["id"], "label": s["label"], "status": self.status(st["id"], s["id"])} for s in self.seats[st["id"]]]
        if method == "POST" and len(parts) == 4 and parts[3] == "quote" and st:
            n = len(body["seatIds"])
            return 200, {"unitPrice": self.money(self.price(st)), "seats": n, "total": self.money(round(self.price(st) * n, 2))}
        if not user:
            return 401, None
        if method == "POST" and len(parts) == 4 and parts[3] == "lock" and st:
            if any((st["id"], s) in self.sold or (self.locks.get((st["id"], s)) not in (None, user) and not self.no_locks) for s in body["seatIds"]):
                return 409, None
            for s in body["seatIds"]:
                self.locks[(st["id"], s)] = user
            return 200, {"seatIds": body["seatIds"], "expiresAt": "2099-01-01T00:00:00.000Z"}
        if (method, path) == ("POST", "/api/checkout"):
            st = next(s for s in self.showtimes if s["id"] == body["showtimeId"])
            if any((st["id"], s) in self.sold or self.locks.get((st["id"], s)) not in (None, user) for s in body["seatIds"]):
                return 409, None
            for s in body["seatIds"]:
                self.sold.add((st["id"], s)); self.locks.pop((st["id"], s), None)
            o = {"id": len(self.orders) + 1, "showtimeId": st["id"], "seatIds": body["seatIds"],
                 "total": round(self.price(st) * len(body["seatIds"]), 2), "user": user}
            self.orders.append(o)
            return 201, {k: o[k] for k in ("id", "showtimeId", "seatIds")} | {"total": self.money(o["total"])}
        if (method, path) == ("GET", "/api/orders"):
            return 200, [{k: o[k] for k in ("id", "showtimeId", "seatIds")} | {"total": self.money(o["total"])} for o in self.orders if o["user"] == user]
        return 404, None


class TestCinemaGate(unittest.TestCase):
    def gate(self, **kw):
        srv = serve(ReferenceCinema(**kw))
        try:
            res = acceptance_check.run(f"http://127.0.0.1:{srv.server_port}", "cinema")
        finally:
            srv.shutdown(); srv.server_close()
        return res, {c["case"]: c["ok"] for c in res["cases"]}

    def test_a_correct_cinema_passes_every_case(self):
        res, _ = self.gate()
        self.assertEqual(res["acceptance_pct"], 100.0, [c for c in res["cases"] if not c["ok"]])
        self.assertEqual(res["domain"], "cinema"); self.assertGreaterEqual(res["total"], 20)

    def test_prices_as_strings_fail_the_json_number_cases_only(self):
        _, cases = self.gate(money_as_string=True)
        failed = sorted(k for k, v in cases.items() if not v)
        self.assertTrue(failed and all("numeric" in k or "JSON number" in k for k in failed), failed)

    def test_ignoring_other_users_locks_is_caught(self):
        _, cases = self.gate(no_locks=True)
        self.assertFalse(cases["lock: another user cannot lock a seat that is locked (409)"])

    def test_unknown_domain_and_iso_dates(self):
        with self.assertRaises(ValueError):
            acceptance_check.run("http://127.0.0.1:1", "library")
        local = _dt.datetime(2030, 1, 2, 20, 0).astimezone()
        self.assertEqual(acceptance_check.local_hm(local.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")), "20:00")

    def test_a_non_json_success_body_keeps_its_status(self):
        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200); self.send_header("Content-Type", "text/plain"); self.end_headers(); self.wfile.write(b"OK")
            def log_message(self, *a):
                pass
        srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            self.assertEqual(acceptance_check.call(f"http://127.0.0.1:{srv.server_port}", "GET", "/health"), (200, "OK"))
        finally:
            srv.shutdown(); srv.server_close()

    def test_the_cinema_seed_buys_seats_through_the_api(self):
        srv = serve(ReferenceCinema())
        try:
            res = pg_seed.seed_cinema(f"http://127.0.0.1:{srv.server_port}", 6, "x")
        finally:
            srv.shutdown(); srv.server_close()
        self.assertEqual((res["users"], res["errors"], res["order_queries"]), (6, 0, 6)); self.assertGreater(res["orders"], 6)


class TestBatchAEvaluatorFixes(unittest.TestCase):
    R = ev.RUBRIC["relational"]

    def test_replica_and_sql_server_ddl_stay_out_of_the_main_schema(self):
        files = [("db/mssql/products.sql", "CREATE TABLE products (id INT IDENTITY(1,1) PRIMARY KEY, name NVARCHAR(100));\nGO\n"),
                 ("db/replica/schema.sql", "CREATE TABLE products (id int PRIMARY KEY);"),
                 ("db/schema.sql", "CREATE TABLE products (id serial PRIMARY KEY, name text NOT NULL, price numeric(10,2));"),
                 ("db/sync.sql", "IF OBJECT_ID('dbo.orders') IS NULL CREATE TABLE dbo.orders (id INT PRIMARY KEY);")]
        s = rs.extract(files, {"sqlStrings": [{"file": "backend/src/db/sqlServerReplica.js", "line": 3, "migration": False,
                                               "text": "CREATE TABLE products (id INT PRIMARY KEY)"}]}, self.R)
        self.assertEqual(sorted(s["tables"]), ["products"])
        self.assertEqual(sorted(s["tables"]["products"]["columns"]), ["id", "name", "price"])  # the main PostgreSQL definition
        self.assertEqual(sorted(x["file"].split(":")[0] for x in s["secondary_sql"]),
                         ["backend/src/db/sqlServerReplica.js", "db/mssql/products.sql", "db/replica/schema.sql", "db/sync.sql"])

    def test_numbered_migrations_are_applied_in_numeric_order(self):
        files = [("migrations/10_add_price.sql", "ALTER TABLE products ADD COLUMN price numeric(10,2);"),
                 ("migrations/2_create.sql", "CREATE TABLE products (id serial PRIMARY KEY);")]
        s = rs.extract(files, {"sqlStrings": []}, self.R)
        self.assertEqual(sorted(s["tables"]["products"]["columns"]), ["id", "price"]); self.assertEqual(s["unparsed"], [])

    def test_health_routes_exclude_resource_sub_routes(self):
        yes = ["/health", "/api/health", "/api/v1/healthz", "/status", "/metrics", "/api/ready"]
        no = ["/api/orders/:id/status", "/orders/{id}/status", "/api/deliveries", "/api/showtimes/:id/seats", "/"]
        self.assertEqual([ev.is_health_route(p) for p in yes], [True] * len(yes))
        self.assertEqual([ev.is_health_route(p) for p in no], [False] * len(no))

    def test_routes_get_their_mount_prefix_and_contract_matching_is_exact(self):
        ast = {"mounts": [{"file": "src/app.js", "path": "/api", "target": "src/routes/index.js"},
                          {"file": "src/routes/index.js", "path": "/orders", "target": "src/routes/orders.js"},
                          {"file": "src/app.js", "path": "/x", "target": None}],
               "routes": [{"file": "src/routes/orders.js", "method": "PATCH", "path": "/:id/status", "obj": "router"},
                          {"file": "src/app.js", "method": "GET", "path": "/health", "obj": "app"},
                          {"file": "src/routes/mystery.js", "method": "GET", "path": "/:id", "obj": "router"}]}
        fr = ev.full_routes(ast)
        self.assertEqual([(r["full_path"], r["resolved"]) for r in fr],
                         [("/api/orders/:id/status", True), ("/health", True), ("/:id", False)])
        contract = [("PATCH", "/orders/{orderId}/status"), ("GET", "/products/{id}")]
        self.assertTrue(ev.route_match(contract, fr[0], ["/api"]))   # under servers[].url
        self.assertFalse(ev.route_match(contract, fr[0], []))        # without the base path it is a different path
        self.assertFalse(ev.route_match(contract, fr[1], ["/api"]))
        self.assertTrue(ev.route_match(contract, fr[2], []))         # unknown prefix: whole trailing segments
        self.assertFalse(ev.route_match([("GET", "/products/{id}")], {**fr[2], "path": "/ducts/{id}", "full_path": "/ducts/:id"}, []))

    def test_mounts_and_validation_from_real_code(self):
        with tempfile.TemporaryDirectory() as t:
            app = Path(t) / "app"; (app / "backend" / "src" / "routes").mkdir(parents=True)
            (app / "backend" / "src" / "app.js").write_text(
                "const express = require('express');\nconst orders = require('./routes/orders');\nconst app = express();\n"
                "app.use('/api/orders', auth, orders);\napp.get('/api/health', (req, res) => res.json({ ok: true }));\nmodule.exports = app;\n", encoding="utf-8")
            (app / "backend" / "src" / "routes" / "orders.js").write_text(
                "const router = require('express').Router();\nconst { body } = require('express-validator');\n"
                "router.post('/', async (req, res) => { const r = await pool.query('SELECT 1'); res.json(JSON.parse(r)); });\n"
                "router.patch('/:id/status', body('status').isString(), async (req, res) => res.json({}));\nmodule.exports = router;\n", encoding="utf-8")
            ast = ev.run_ast(app, Path(t))
        self.assertEqual([m["target"] for m in ast["mounts"]], ["backend/src/routes/orders.js"])
        got = {(r["method"], r["full_path"]): r["validated"] for r in ev.full_routes(ast)}
        self.assertEqual(got, {("POST", "/api/orders"): False, ("PATCH", "/api/orders/:id/status"): True, ("GET", "/api/health"): False})

    def test_readme_declarations_need_whole_words(self):
        readme = "Log in with your account, browse the catalog and the API under /api. Run npm install, then latest versions."
        hits = {k for k, rx in ev.DECLARED_PATTERNS.items() if rx and re.search(rx, readme, re.I)}
        self.assertEqual(hits, {"technologies"})
        self.assertTrue(re.search(ev.DECLARED_PATTERNS["observability"], "Structured logging with pino", re.I))
        self.assertTrue(re.search(ev.DECLARED_PATTERNS["contracts"], "The OpenAPI document is in docs/", re.I))

    def test_children_of_external_base_classes_are_not_a_wide_hierarchy(self):
        cls = [{"name": f"E{i}", "file": "errors.js", "extends": "Error"} for i in range(12)] + \
              [{"name": f"C{i}", "file": "c.jsx", "extends": "React.Component"} for i in range(12)]
        m = {"ast": {"classes": cls}, "graph": {"modules": [{"source": "errors.js", "deps": []}]}}
        crit = ev.eval_hierarchies(m, {}, Opts)[0]
        self.assertTrue(crit["C2"]["ok"])
        own = cls + [{"name": "Base", "file": "base.js", "extends": None}] + [{"name": f"K{i}", "file": f"k{i}.js", "extends": "Base"} for i in range(11)]
        self.assertFalse(ev.eval_hierarchies({**m, "ast": {"classes": own}}, {}, Opts)[0]["C2"]["ok"])

    def test_a_coverage_report_without_branches_does_not_fail_branch_coverage(self):
        a = {"switchesMissingDefault": [], "fallthrough": [], "labeledJumps": []}
        m = {"ast": a, "tests_static": {"test_cases": 3, "test_files": ["t.test.js"]},
             "tests_run": {"executed": True, "ran_any": True, "all_passed": True, "lines_total": 100, "lines_cov": 80, "br_total": 0, "br_cov": 0}}
        crit, met, _, finding, _ = ev.eval_tests(m, {}, Opts)
        self.assertNotIn("C4", crit); self.assertIsNone(met["branch_coverage"]); self.assertIn("not applicable", finding)
        self.assertEqual(ev.level_from(crit)[0], "Meets")

    def test_judge_model_identity(self):
        self.assertEqual(judge.norm_model("us.anthropic.claude-sonnet-5-5-20260101-v1:0"), "claude-sonnet-5-5")
        self.assertEqual(judge.norm_model("anthropic/claude-opus-5-5[1m]"), "claude-opus-5-5")
        self.assertTrue(judge.same_model("claude-sonnet-5-5", "Claude-Sonnet-5-5[1m]"))
        self.assertTrue(judge.same_model("claude-sonnet-5-5", "sonnet"))        # an alias of the same family
        self.assertFalse(judge.same_model("claude-sonnet-5-5", "claude-opus-5-5"))
        self.assertFalse(judge.same_model("gpt-6.1-sol", "claude-opus-5-5"))

    def test_judge_refuses_when_the_generator_model_is_unknown(self):
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / "meta.json").write_text(json.dumps({"model": "n/a"}), encoding="utf-8")
            with mock.patch.object(sys, "argv", ["judge.py", t, "--model", "claude-opus-5-5"]), self.assertRaises(SystemExit) as cm:
                judge.main()
        self.assertIn("not recorded", str(cm.exception))


class TestBatchARunExperiment(unittest.TestCase):
    def args(self, **kw):
        return argparse.Namespace(**{"agent_cmd": None, "model": "m1", "domain": "cinema", "skip_acceptance": False, **kw})

    def test_the_prompt_goes_on_stdin_unless_the_template_asks_for_it(self):
        cmd, stdin = run_experiment.agent_command("claude", self.args(), "line 1\nline 2")
        self.assertEqual((cmd[:2], cmd[-2:], stdin), (["claude", "-p"], ["--model", "m1"], "line 1\nline 2"))
        self.assertNotIn("line 1\nline 2", " ".join(cmd))
        cmd, stdin = run_experiment.agent_command("codex", self.args(), "p")
        self.assertEqual((cmd[-3], stdin), ("-", "p"))
        cmd, stdin = run_experiment.agent_command("claude", self.args(agent_cmd="my-agent --run {prompt}"), "p")
        self.assertEqual((cmd, stdin), (["my-agent", "--run", "p"], None))

    def test_sh_resolves_the_executable_and_feeds_stdin(self):
        with tempfile.TemporaryDirectory() as t:
            log = Path(t) / "log.txt"
            with open(log, "w", encoding="utf-8") as f:
                # the child decodes UTF-8 explicitly, as the agents' CLIs (Node) do; Python would use the Windows code page
                rc = run_experiment.sh(["python", "-c", "import sys; print(sys.stdin.buffer.read().decode('utf-8').upper().encode('ascii', 'backslashreplace').decode())"],
                                       log=f, stdin_text="héllo\nworld")
            out = log.read_text(encoding="utf-8").split()  # Windows text mode may turn \n into \r\n: compare the words
            self.assertEqual(rc, 0); self.assertEqual(out, ["H\\xc9LLO", "WORLD"])
        self.assertEqual(run_experiment.resolve(["python", "-V"])[0], shutil.which("python"))
        self.assertEqual(run_experiment.sh(["surely-not-an-installed-agent-xyz"]), 127)

    def test_the_gate_is_not_run_on_a_project_that_implements_r2(self):
        with tempfile.TemporaryDirectory() as t:
            project, exp = Path(t) / "p", Path(t) / "e"; project.mkdir(); exp.mkdir()
            (project / "r2-additional-requirements.md").write_text("x", encoding="utf-8")
            with mock.patch.object(run_experiment, "acceptance") as acc, contextlib.redirect_stdout(io.StringIO()):
                meta = {"acceptance": {"passed": 20, "total": 20}}
                run_experiment.gate_after_phases(["r2"], project, exp, "r", self.args(), meta)
                self.assertEqual(meta["acceptance"], {"passed": 20, "total": 20})        # the result after phase initial is kept
                meta = {}
                run_experiment.gate_after_phases(["r2"], project, exp, "r", self.args(), meta)
                self.assertTrue(meta["acceptance"]["skipped"]); self.assertIn("original", meta["acceptance"]["reason"])
                acc.assert_not_called()
                (project / "r2-additional-requirements.md").unlink()
                acc.return_value = {"passed": 1, "total": 1, "acceptance_pct": 100.0}
                run_experiment.gate_after_phases([], project, exp, "r", self.args(), meta)
                acc.assert_called_once(); self.assertEqual(acc.call_args.kwargs["domain"], "cinema")
                self.assertEqual(json.loads((exp / "acceptance.json").read_text(encoding="utf-8"))["state"], "project as found")


import importlib  # noqa: E402
from evaluator.collectors import documents as _documents  # noqa: E402


class TestVersionedDocuments(unittest.TestCase):
    ER_OLD = "```mermaid\nerDiagram\n  USERS {\n    int id PK\n  }\n```\n"
    ER_NEW = "```mermaid\nerDiagram\n  USERS {\n    int id PK\n    string role\n  }\n  AUDIT_LOG {\n    int id PK\n  }\n```\n"

    def app(self, t, files):
        for rel_path, text in files.items():
            p = Path(t) / rel_path; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text, encoding="utf-8")
        return Path(t)

    def test_the_er_model_of_the_latest_version_comes_first(self):
        with tempfile.TemporaryDirectory() as t:
            app = self.app(t, {"docs/entity-relationship-model.md": self.ER_OLD, "docs/R2/entity-relationship-model.md": self.ER_NEW})
            er = ra.load_er(app, RUBRIC_REL)
            self.assertEqual((er["file"], er["version"], sorted(er["entities"])), ("docs/R2/entity-relationship-model.md", "R2", ["AUDIT_LOG", "USERS"]))

    def test_another_name_in_the_version_folder_counts_if_it_has_the_diagram(self):
        with tempfile.TemporaryDirectory() as t:  # what the codex apps delivered: docs/r2/data-model.md
            app = self.app(t, {"docs/entity-relationship-model.md": self.ER_OLD, "docs/r2/api.md": "# API",
                               "docs/r2/data-model.md": self.ER_NEW})
            self.assertEqual(ra.load_er(app, RUBRIC_REL)["file"], "docs/r2/data-model.md")

    def test_without_a_version_folder_the_original_path_is_used(self):
        with tempfile.TemporaryDirectory() as t:
            app = self.app(t, {"docs/Entity-Relationship-Model.md": self.ER_OLD, "docs/R1/x.md": self.ER_NEW})
            er = ra.load_er(app, RUBRIC_REL)
            self.assertEqual((er["file"], er["version"]), ("docs/Entity-Relationship-Model.md", None))
        self.assertIn("docs/R2/entity-relationship-model.md", ra.er_searched(RUBRIC_REL))

    def test_the_readme_of_the_latest_version_comes_first(self):
        with tempfile.TemporaryDirectory() as t:
            app = self.app(t, {"README.md": "old", "backend/README.md": "backend"})
            self.assertEqual(_documents.readme_text(app), "old")
            self.app(t, {"docs/R2/README.md": "new"})
            self.assertEqual(_documents.readme_text(app), "new")
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual(_documents.readme_text(self.app(t, {"backend/README.md": "backend"})), "backend")


class TestModularLayout(unittest.TestCase):
    """One module per decision point, the facade keeps the public names."""

    def test_every_decision_point_has_its_own_module(self):
        from evaluator import points
        self.assertEqual(set(points.EVALUATORS), set(ev.RUBRIC["points"]))
        for pid, fn in points.EVALUATORS.items():
            self.assertEqual(fn.__module__, f"evaluator.points.{pid}")
            self.assertTrue(importlib.import_module(f"evaluator.points.{pid}").__doc__.startswith("Decision point"))

    def test_the_facade_re_exports_what_other_scripts_use(self):
        for name in ("RUBRIC", "model_missing", "MODEL_ERROR", "record_generator_model", "run_ast", "level_from", "evaluate_profile",
                     "write_outputs", "route_match", "dead_files", "token_columns", "cmd_run", "cmd_aggregate"):
            self.assertTrue(hasattr(ev, name), name)
        self.assertIs(ev.RUBRIC, importlib.import_module("evaluator.common").RUBRIC)  # one shared rubric object


class TestRescore(unittest.TestCase):
    """Re-scoring from metrics.json: the same result as `run`, and the inputs added after the collection are read fresh."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(); cls.root = Path(cls.tmp.name)
        cls.out = cls.root / "claude-n1-r1"
        ns = argparse.Namespace(app=str(FIX / "sequelize_app"), out=str(cls.out), agent="claude", model="claude-sonnet-5-5", level="N1",
                                domain="ecommerce", run_id="claude-n1-r1", manual=None, layers=None, test_cmd=None, run_tests=False,
                                offline=True, accept_heuristics=False, allow_missing_model=False)
        with contextlib.redirect_stdout(io.StringIO()):
            ev.cmd_run(ns)
        cls.after_run = {f: (cls.out / f).read_text(encoding="utf-8") for f in ("profile.json", "scorecard.json", "profile.md")}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def point(self, pid):
        return next(p for p in json.loads((self.out / "scorecard.json").read_text(encoding="utf-8"))["points"] if p["id"] == pid)

    def test_1_rescore_reproduces_the_outputs_of_run(self):
        meta, pts, prof = ev.rescore(self.out)
        self.assertEqual(meta["run_id"], "claude-n1-r1")
        for f, text in self.after_run.items():
            self.assertEqual((self.out / f).read_text(encoding="utf-8"), text, f)

    def test_2_dv8_values_and_a_manual_review_added_later_are_read(self):
        self.assertIsNone(self.point("cohesion")["criteria"]["C2"]["ok"])  # DV8 DL pending after run
        (self.out / "dv8").mkdir(exist_ok=True)
        (self.out / "dv8" / "dv8_metrics.json").write_text(json.dumps({"DL": 0.9, "PC": 0.1, "_origin": {}}), encoding="utf-8")
        (self.out / "manual_review.json").write_text(json.dumps({"cohesion": {"C3": {"ok": True, "note": "checked"}}}), encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            ev.cmd_aggregate(argparse.Namespace(dir=str(self.root), out=None))  # aggregate used to keep the manual.json of the run
        c = self.point("cohesion")["criteria"]
        self.assertEqual((c["C2"]["ok"], c["C2"]["value"], c["C3"]["ok"], c["C3"]["source"]), (True, 0.9, True, "manual"))
        used = json.loads((self.out / "manual.json").read_text(encoding="utf-8"))  # what the scoring used, kept for traceability
        self.assertEqual((used["dv8"]["DL"], used["dv8"]["PC"]), (0.9, 0.1))

    def test_3_the_rescore_command(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ev.cmd_rescore(argparse.Namespace(res=[str(self.out)]))
        self.assertIn("Re-scored claude-n1-r1: Maintainability:", out.getvalue())
        r = subprocess.run([sys.executable, str(SRC / "evaluate.py"), "rescore", str(self.out)], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stderr); self.assertIn("Re-scored", r.stdout)


class TestCliCollectsOnce(unittest.TestCase):
    def run_app(self, tmp, **over):
        o = {"domain": "ecommerce", "rep": 1, "results": str(Path(tmp) / "res"), "model": "m", "skip_tests": True, "offline": True,
             "accept_heuristics": False, "usage_dir": str(Path(tmp) / "usage"), "postgres": False, "judge": "j", "judge_votes": 3,
             "judge_cmd": None, "allow_same_model": False, "rescore_only": False, **over}
        calls = []
        def fake(cmd, cwd=None, timeout=1800):
            calls.append(Path(cmd[1]).name + (":" + cmd[2] if Path(cmd[1]).name == "evaluate.py" else ""))
            return 0, "Judge j: 1 decision(s)"
        app = Path(tmp) / "claude-n1"; app.mkdir(exist_ok=True)
        with mock.patch.object(cli, "execute", side_effect=fake):
            run_id, summary = cli.evaluate_app(app, o, "dv8.exe")
        return calls, summary

    def test_dv8_and_the_judge_re_score_instead_of_evaluating_again(self):
        with tempfile.TemporaryDirectory() as t:
            calls, _ = self.run_app(t)
        self.assertEqual(calls, ["evaluate.py:run", "dv8_metrics.py", "evaluate.py:rescore", "manual_template.py", "judge.py", "evaluate.py:rescore"])

    def test_rescore_only_does_not_collect(self):
        with tempfile.TemporaryDirectory() as t:
            calls, summary = self.run_app(t, rescore_only=True)
            self.assertEqual(calls, []); self.assertIn("evaluate it once without --rescore", summary)
            (Path(t) / "res" / "claude-n1-ecommerce-r1").mkdir(parents=True, exist_ok=True)
            (Path(t) / "res" / "claude-n1-ecommerce-r1" / "metrics.json").write_text("{}", encoding="utf-8")
            calls, summary = self.run_app(t, rescore_only=True)
        self.assertEqual(calls, ["evaluate.py:rescore"]); self.assertFalse(summary.startswith("ERROR"))


class TestPointWeights(unittest.TestCase):
    """Weights of the decision points inside each subcharacteristic (`point_weights` in rubric.json)."""

    LEVEL = {0: "Fails", 0.5: "Partial", 1: "Meets"}

    def pts(self, scores=None):
        scores = scores or {}
        return [{"id": pid, "name": d["name"], "subcharacteristics": d["subcharacteristics"], "complete": True,
                 "level": self.LEVEL[scores.get(pid, 0)], "level_min": self.LEVEL[scores.get(pid, 0)], "level_max": self.LEVEL[scores.get(pid, 0)],
                 "pending_criteria": [], "score_min": scores.get(pid, 0), "score_max": scores.get(pid, 0)}
                for pid, d in ev.RUBRIC["points"].items()]

    def test_without_point_weights_each_subcharacteristic_is_the_plain_mean(self):
        with mock.patch.dict(ev.RUBRIC, {"point_weights": {}}):
            prof = ev.profile(self.pts({"tests": 1}))
        self.assertEqual(prof["subcharacteristics"]["Testability"]["min"], 50.0)
        self.assertEqual(prof["maintainability_min"], 15.0)

    def test_a_point_weight_makes_its_subcharacteristic_a_weighted_mean(self):
        with mock.patch.dict(ev.RUBRIC, {"point_weights": {"tests": 3}}):
            prof = ev.profile(self.pts({"tests": 1}))
        self.assertEqual(prof["subcharacteristics"]["Testability"]["min"], 75.0)
        self.assertEqual(prof["maintainability_min"], 22.5)

    def test_the_impact_of_the_risk_list_follows_the_point_weights(self):
        with mock.patch.dict(ev.RUBRIC, {"point_weights": {}}):
            r = {x["id"]: x["impact"] for x in ev.risk_summary(self.pts())}
        self.assertEqual((r["tests"], r["layers"]), (15.0, 3.4))
        with mock.patch.dict(ev.RUBRIC, {"point_weights": {"tests": 3}}):
            r = {x["id"]: x["impact"] for x in ev.risk_summary(self.pts())}
        self.assertEqual((r["tests"], r["contracts"]), (22.5, 10.9))

    def test_the_panel_scenario_reproduces_the_weighted_profile(self):
        from evaluator import sensitivity as S
        with mock.patch.dict(ev.RUBRIC, {"point_weights": {"tests": 3, "layers": 2}}):
            p = self.pts({"tests": 1, "layers": 0.5, "observability": 1}); prof = ev.profile(p)
            panel = next(spec for name, _, spec in S.scenarios() if name == "panel")
            self.assertEqual(S.overall(p, panel), (prof["maintainability_min"], prof["maintainability_max"]))

    def test_a_point_weight_that_is_not_a_positive_number_is_rejected(self):
        from evaluator.common import point_weight
        for bad in (0, -1, "2", True):
            with mock.patch.dict(ev.RUBRIC, {"point_weights": {"tests": bad}}):
                with self.assertRaises(ValueError):
                    point_weight("tests")
        with mock.patch.dict(ev.RUBRIC, {"point_weights": {"_comment": "only a comment"}}):
            self.assertEqual(point_weight("tests"), 1)


class TestWeightSensitivity(unittest.TestCase):
    """The overall score and the ranking of the runs under other weights (the panel's Kendall W is not significant)."""

    @staticmethod
    def pts(good, pending=()):
        out = []
        for pid, d in ev.RUBRIC["points"].items():
            v = 1.0 if pid in good else 0.0
            out.append({"id": pid, "subcharacteristics": d["subcharacteristics"], "complete": pid not in pending,
                        "score_min": 0.0 if pid in pending else v, "score_max": 1.0 if pid in pending else v})
        return out

    def runs(self):
        # A is good only at tests (Testability, the heaviest weight); B at observability + configuration
        return [({"run_id": "claude-n1-r1", "agent": "claude", "level": "N1"}, self.pts({"tests"})),
                ({"run_id": "codex-n2-r1", "agent": "codex", "level": "N2"}, self.pts({"observability", "configuration"}))]

    def scenario(self, s, name):
        return next(x for x in s["scenarios"] if x["name"] == name)

    def test_panel_scenario_reproduces_the_profile(self):
        from evaluator import sensitivity as S
        for good, pend in (({"tests", "layers"}, ()), ({"contracts"}, ("cohesion",))):
            p = self.pts(good, pend); prof = ev.profile(p)
            panel = next(spec for name, _, spec in S.scenarios() if name == "panel")
            self.assertEqual(S.overall(p, panel),
                             (prof["maintainability_min"], prof["maintainability_max"]))

    def test_a_ranking_that_depends_on_the_weights_is_flagged(self):
        s = ev.sensitivity(self.runs())
        self.assertEqual(self.scenario(s, "panel")["ranks"], {"claude-n1-r1": 1, "codex-n2-r1": 2})
        self.assertEqual(self.scenario(s, "panel")["scores"]["claude-n1-r1"], [15.0, 15.0])
        uni = self.scenario(s, "uniform")
        self.assertEqual((uni["ranks"]["codex-n2-r1"], uni["tau_b"], uni["same_top"], uni["max_rank_shift"]), (1, -1.0, False, 1))
        self.assertEqual(self.scenario(s, "without_tests")["scores"]["claude-n1-r1"], [0.0, 0.0])
        self.assertTrue(self.scenario(s, "without_layers")["same_top"])
        self.assertFalse(s["stable"]["top"]); self.assertFalse(s["stable"]["level"]); self.assertFalse(s["stable"]["agent"])
        self.assertIn("uniform", s["changes"]["top"]); self.assertIn("equal_points", s["changes"]["level"])
        self.assertEqual(s["runs"]["claude-n1-r1"], {"panel_rank": 1, "best_rank": 1, "worst_rank": 2, "score_low": 0.0, "score_high": 30.0})  # 30: without contracts, Testability is tests alone
        md = "\n".join(ev.sensitivity_md(s))
        self.assertIn("**Best run**: changes under `uniform`", md); self.assertIn("| uniform | ", md)

    def test_a_robust_ranking_holds_in_every_scenario(self):
        s = ev.sensitivity([({"run_id": "a", "agent": "x", "level": "N3"}, self.pts(set(ev.RUBRIC["points"]) - {"tests"})),
                            ({"run_id": "b", "agent": "y", "level": "N1"}, self.pts({"layers"}))])
        self.assertTrue(all(s["stable"].values())); self.assertEqual(s["stable"]["min_tau_b"], 1.0)
        self.assertIn("**Best run**: holds in every scenario", "\n".join(ev.sensitivity_md(s)))

    def test_ties_ranks_and_tau(self):
        from evaluator import sensitivity as S
        self.assertEqual(S.ranks({"a": 3, "b": 3, "c": 1}), {"a": 1.5, "b": 1.5, "c": 3})
        self.assertEqual(S.kendall_tau_b({"a": 1, "b": 2, "c": 3}, {"a": 1, "b": 2, "c": 3}), 1.0)
        self.assertIsNone(S.kendall_tau_b({"a": 1}, {"a": 1}))

    def test_weight_sets_of_the_rubric_are_normalized_scenarios(self):
        extra = {"weight_sets": {"E1": {"Testability": 1, "Analyzability": 1, "Modularity": 1, "Modifiability": 1}, "_note": "x"}}
        with mock.patch.dict(ev.RUBRIC, {"sensitivity": extra}):
            s = ev.sensitivity(self.runs())
        self.assertEqual(self.scenario(s, "E1")["scores"], self.scenario(s, "uniform")["scores"])
        self.assertNotIn("_note", [x["name"] for x in s["scenarios"]])

    def test_a_single_run_has_no_ranking_to_compare(self):
        s = ev.sensitivity(self.runs()[:1])
        self.assertIn("A single run", "\n".join(ev.sensitivity_md(s)))


class TestLint(unittest.TestCase):
    """ESLint + eslint-plugin-sonarjs (lint_metrics.js): ISO/IEC 5055 weaknesses that no point scores, S1192 and S3776 from the rules
    themselves, and the cross-check of the McCabe count."""

    APP = FIX / "lint_app"

    @classmethod
    def setUpClass(cls):
        from evaluator.collectors import lint
        cls.lint = lint
        cls.res = None
        if lint.available():
            with tempfile.TemporaryDirectory() as t:
                cls.res = lint.run_lint(cls.APP, Path(t), ["backend/src/bad.js", "backend/src/typed.ts", "frontend/src/App.jsx"])

    def setUp(self):
        if self.res is None:
            self.skipTest("ESLint is not installed (npm install)")

    def test_every_mapped_weakness_is_detected_once_per_line(self):
        r = self.res
        self.assertTrue(r["ok"], r); self.assertEqual(r["parse_errors"], [])  # .ts with <T>x and .jsx both parse
        self.assertEqual(r["versions"]["eslint-plugin-sonarjs"], "4.2.2")
        self.assertEqual({k: len(v) for k, v in r["ascmm"].items()},
                         {"CWE-480": 3, "CWE-570/571": 2, "CWE-783": 3, "CWE-1095": 1, "CWE-1085": 1})
        # no-mixed-operators reports each operator of `a && b || c`: one occurrence; the eslint-disable comment of App.jsx is ignored
        self.assertEqual(sorted((x["file"], x["line"]) for x in r["ascmm"]["CWE-783"]),
                         [("backend/src/bad.js", 22), ("backend/src/bad.js", 23), ("frontend/src/App.jsx", 4)])
        self.assertEqual((r["ascmm"]["CWE-1085"][0]["line"], r["ascmm"]["CWE-1085"][0]["end_line"]), (37, 38))

    def test_s1192_s3776_and_complexity_come_from_the_rules(self):
        r = self.res
        self.assertEqual(r["dup_strings"], [{"file": "backend/src/bad.js", "line": 2, "literal": '"a long literal value"', "times": 3}])  # application/json ignored
        self.assertIn({"file": "backend/src/bad.js", "line": 13, "value": 4}, r["cognitive"])
        self.assertIn({"file": "backend/src/bad.js", "line": 13, "value": 5}, r["mccabe"])

    def test_the_points_and_indicators_use_the_lint_result(self):
        with tempfile.TemporaryDirectory() as t:
            ast = ev.run_ast(self.APP, Path(t))
        m = {"ast": ast, "lint": self.res, "env_example": False, "contract": {}, "schema": {"tables": {}}, "readme": ""}
        crit, met, _, _, _ = ev.eval_configuration(m, {}, Opts())
        self.assertEqual(crit["C2"]["value"], {"a long literal value (backend/src/bad.js)": 3})
        self.assertTrue(crit["C2"]["source"].startswith("auto (eslint-plugin-sonarjs 4.2.2"))
        _, met, _, finding, _ = ev.eval_cyclomatic({**m, "duplication": {}}, {}, Opts())
        self.assertEqual((met["cognitive_source"], met["mccabe_eslint"]["equal_pct"]), ("SonarJS S3776", 100.0))
        rows = {r[0]: r for r in __import__("evaluator.supplementary", fromlist=["x"]).ascmm_indicators(m)}
        self.assertEqual({k: v[3] for k, v in rows.items()},
                         {"ascmm_cwe1064": 1, "ascmm_cwe480": 3, "ascmm_cwe570_571": 2, "ascmm_cwe783": 3, "ascmm_cwe1095": 1, "ascmm_cwe1085": 1})
        self.assertEqual(rows["ascmm_cwe1085"][7], ["backend/src/bad.js:36 commentedOut (2 of 5 lines)"])


class TestLintFallback(unittest.TestCase):
    """Without a lint result (ESLint missing or an old metrics.json) S1192 is pending and the lint-only measures are not taken."""

    def model(self, lint=None):
        fns = [{"file": "a.js", "line": 1, "name": "f", "test": False, "cc": 3, "loc": 10, "params": list("abcdefgh")},
               {"file": "a.js", "line": 20, "name": "g", "test": False, "cc": 25, "loc": 100, "params": []}]
        m = {"ast": {"functions": fns, "files": [{"path": "a.js", "loc": 200, "test": False}], "networkLiterals": [], "envFiles": {}},
             "env_example": True, "duplication": {}}
        if lint is not None:
            m["lint"] = lint
        return m

    def test_without_eslint_nothing_falls_back_to_an_approximation(self):
        from evaluator.supplementary import ascmm_indicators
        for lint in (None, {"ok": False, "error": "ESLint is not installed"}):
            m = self.model(lint)
            self.assertIsNone(ev.eval_configuration(m, {}, Opts())[0]["C2"]["ok"])  # pending, not approximated
            _, met, _, finding, _ = ev.eval_cyclomatic(m, {}, Opts())
            self.assertEqual((met["cognitive_source"], met["functions_cog_above_threshold"]), (None, None))
            self.assertNotIn("mccabe_eslint", met); self.assertIn("Cognitive complexity not measured (ESLint did not run", finding)
            rows = {r[0]: r for r in ascmm_indicators(m)}
            self.assertEqual((rows["ascmm_cwe1064"][3], rows["ascmm_cwe1064"][5]), (1, False))  # from the AST, no ESLint needed
            self.assertEqual((rows["ascmm_cwe480"][3], rows["ascmm_cwe480"][5]), (None, None))
            self.assertIn("ESLint did not run", rows["ascmm_cwe480"][6])

    def test_parse_errors_leave_the_zero_counts_unproven(self):
        from evaluator.supplementary import ascmm_indicators
        lint = {"ok": True, "versions": {}, "files": 2, "parse_errors": [{"file": "b.js", "line": 3, "message": "Parsing error"}],
                "mccabe": [], "cognitive": [], "dup_strings": [],
                "ascmm": {"CWE-480": [{"file": "a.js", "line": 2, "end_line": 2, "rule": "use-isnan", "message": "x"}], "CWE-783": []}}
        rows = {r[0]: r for r in ascmm_indicators(self.model(lint))}
        self.assertFalse(rows["ascmm_cwe480"][5]); self.assertIsNone(rows["ascmm_cwe783"][5])
        self.assertIn("could not parse 1 file(s): b.js", rows["ascmm_cwe783"][6])

    def test_summarize_dedupes_only_the_weakness_rules(self):
        from evaluator.collectors import lint
        msg = lambda rule, line, text: {"rule": rule, "file": "a.js", "line": line, "endLine": line, "message": text}  # noqa: E731
        r = lint.summarize({"versions": {}, "files": 1, "parse_errors": [], "messages": [
            msg("no-mixed-operators", 3, "mix"), msg("no-mixed-operators", 3, "mix"),
            msg("complexity", 5, "Arrow function has a complexity of 2. Maximum allowed is 0."),
            msg("complexity", 5, "Function 'x' has a complexity of 4. Maximum allowed is 0."),
            msg("sonarjs/cognitive-complexity", 5, "Refactor this function to reduce its Cognitive Complexity from 7 to the 0 allowed."),
            msg("sonarjs/no-duplicate-string", 6, "Define a constant instead of duplicating this literal 4 times.")]},
            {"no-mixed-operators": "CWE-783"})
        self.assertEqual(len(r["ascmm"]["CWE-783"]), 1)
        self.assertEqual([x["value"] for x in r["mccabe"]], [2, 4])  # two functions on one line are both kept
        self.assertEqual((r["cognitive"][0]["value"], r["dup_strings"][0]["times"]), (7, 4))

    def test_commented_out_code_is_measured_per_function(self):
        from evaluator.supplementary import commented_out_functions
        fns = self.model()["ast"]["functions"]
        reps = [{"file": "a.js", "line": 3, "end_line": 3}, {"file": "a.js", "line": 50, "end_line": 51}]
        # f: 1 of 10 lines (10%) > 2%; g: 2 of 100 lines (2%) is not above 2%
        self.assertEqual([(f["name"], n) for f, n in commented_out_functions(fns, reps, 2.0)], [("f", 1)])

    def test_cross_check_matches_by_file_and_line(self):
        from evaluator.points.cyclomatic import cross_check
        fns = self.model()["ast"]["functions"]
        x = cross_check(fns, [{"file": "a.js", "line": 1, "value": 3}, {"file": "a.js", "line": 20, "value": 27}, {"file": "b.js", "line": 1, "value": 1}], 20)
        self.assertEqual((x["matched"], x["equal_pct"], x["max_abs_diff"], x["above_threshold"], x["X"]), (2, 50.0, 2, 1, round(1 - 1 / 3, 4)))


class TestKnip(unittest.TestCase):
    """Knip (knip_metrics.js) over tests/fixtures/knip_app: a root package with scripts, an Express backend with Jest and a Vite frontend.
    Its jest.config.js and vite.config.js write EXECUTED*.txt if they are run: they must not be."""

    APP = FIX / "knip_app"

    @classmethod
    def setUpClass(cls):
        from evaluator.collectors import knip
        cls.res = None
        if knip.available():
            with tempfile.TemporaryDirectory() as t:
                cls.res = knip.run_knip(cls.APP.resolve(), Path(t))
            cls.executed = sorted(p.name for p in cls.APP.rglob("EXECUTED*"))
            for p in cls.APP.rglob("EXECUTED*"):
                p.unlink()

    def setUp(self):
        if self.res is None:
            self.skipTest("Knip is not installed (npm install)")

    def test_no_file_of_the_app_is_executed(self):
        self.assertEqual(self.executed, [])
        self.assertEqual(self.res["config_load_errors"], [])  # the configs are parsed as entries, not loaded
        self.assertEqual(self.res["overridden_plugins"], {"backend": ["jest"], "frontend": ["vite"]})

    def test_dead_files_by_reachability(self):
        self.assertTrue(self.res["ok"], self.res)
        # deadA and deadB import each other: a fan-in count would miss them. migrate.js (a script), the migration (entry_globs),
        # the test (Jest) and main.jsx (Vite) are reachable
        self.assertEqual(sorted(self.res["files"]), ["backend/src/deadA.js", "backend/src/deadAlone.js", "backend/src/deadB.js",
                                                     "frontend/src/components/Unused.jsx", "scripts/old.js"])

    def test_dependencies(self):
        self.assertEqual(sorted(self.res["dependencies"]), ["backend:lodash", "frontend:axios"])
        self.assertNotIn("frontend:@vitejs/plugin-react", self.res["devDependencies"])  # imported by vite.config.js, read statically
        self.assertNotIn("backend:supertest", self.res["devDependencies"])  # used by the Jest test
        self.assertEqual(self.res["unlisted"], [])  # a nested package's imports are not charged to the root package.json


class TestNoExecGuard(unittest.TestCase):
    """no_exec_guard.mjs: with NO_EXEC_ROOT set, importing or requiring a file under it fails before the file runs."""

    def test_import_and_require_are_refused(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t) / "app"; root.mkdir()
            (root / "a.mjs").write_text("import fs from 'node:fs'; fs.writeFileSync(new URL('./RAN_A', import.meta.url), 'x');", encoding="utf-8")
            (root / "b.cjs").write_text("require('fs').writeFileSync(__dirname + '/RAN_B', 'x');", encoding="utf-8")
            probe = Path(t) / "probe.mjs"
            probe.write_text("\n".join([
                "import { createRequire } from 'node:module'; const out = [];",
                f"try {{ await import({json.dumps((root / 'a.mjs').as_uri())}); out.push('a ran'); }} catch (e) {{ out.push(e.code); }}",
                f"try {{ createRequire(import.meta.url)({json.dumps(str(root / 'b.cjs'))}); out.push('b ran'); }} catch (e) {{ out.push(e.code); }}",
                "console.log(out.join(','));"]), encoding="utf-8")
            p = subprocess.run(["node", "--import", (ROOT / "js" / "tools" / "no_exec_guard.mjs").as_uri(), str(probe)], capture_output=True, text=True,
                               env={**os.environ, "NO_EXEC_ROOT": str(root)}, timeout=60)
            self.assertEqual(p.stdout.strip(), "NO_EXEC_GUARD,NO_EXEC_GUARD", p.stderr)
            self.assertEqual(sorted(x.name for x in root.iterdir()), ["a.mjs", "b.cjs"])  # nothing was written


class TestDependencyFreshness(unittest.TestCase):
    """Technologies on the resolved versions and as of a reference date: lockfiles, latest version and libyear from the npm `time`
    data, OSV advisories in force at as_of, and the older metrics.json format."""

    LOCK = {"lockfileVersion": 3, "packages": {"": {"name": "app"}, "node_modules/express": {"version": "4.18.2"},
                                              "node_modules/jest": {"version": "29.7.0", "dev": True},
                                              "node_modules/express/node_modules/qs": {"version": "6.11.0"},
                                              "node_modules/local": {"link": True, "resolved": "../local"}}}

    def test_lockfile_versions(self):
        from evaluator.collectors import packages as pk
        self.assertEqual((pk.direct_version(self.LOCK, "express"), pk.direct_version(self.LOCK, "react")), ("4.18.2", None))
        self.assertEqual(pk.direct_version({"lockfileVersion": 1, "dependencies": {"express": {"version": "4.17.1"}}}, "express"), "4.17.1")
        self.assertEqual(sorted((p["name"], p["version"], p["dev"]) for p in pk.lock_packages(self.LOCK)),
                         [("express", "4.18.2", False), ("jest", "29.7.0", True), ("qs", "6.11.0", False)])

    def test_the_apps_lockfile_is_used_only_when_it_pins_every_direct_dependency(self):
        from evaluator.collectors import packages as pk
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            (d / "package.json").write_text(json.dumps({"dependencies": {"express": "^4"}, "devDependencies": {"jest": "^29"}}), encoding="utf-8")
            (d / "package-lock.json").write_text(json.dumps(self.LOCK), encoding="utf-8")
            with mock.patch.object(pk, "sh") as sh:
                self.assertEqual(pk.resolve_lock(d, "2025-01-15")[1], "lockfile"); sh.assert_not_called()
            (d / "package.json").write_text(json.dumps({"dependencies": {"express": "^4", "pg": "^8"}}), encoding="utf-8")
            with mock.patch.object(pk, "sh", return_value=(1, "", "no network")) as sh:
                self.assertEqual(pk.resolve_lock(d, "2025-01-15"), (None, None))  # stale lockfile: npm resolves again, as of the date
            self.assertIn("--before=2025-01-15T23:59:59Z", sh.call_args[0][0])

    def times(self):
        return {"created": "2014-01-01T00:00:00Z", "4.18.2": "2022-10-08T00:00:00Z", "4.21.0": "2024-09-11T00:00:00Z",
                "5.0.0": "2024-09-10T00:00:00Z", "5.0.1": "2024-10-08T00:00:00Z", "5.1.0": "2025-03-31T00:00:00Z", "6.0.0-beta.1": "2025-01-01T00:00:00Z"}

    def dependency(self, as_of, resolved="4.18.2"):
        from evaluator.collectors import packages as pk
        npm = lambda args: self.times() if args[1] == "time" else ("Use 5" if args[0] == "express@4.18.2" else None)  # noqa: E731
        with mock.patch.object(pk, "npm_json", side_effect=npm):
            return pk.dependency({"pkg": "express", "spec": "^4", "dir": ".", "dev": False, "resolved": resolved, "resolved_source": "lockfile"}, as_of)

    def test_latest_version_and_libyear_as_of_the_reference_date(self):
        i = self.dependency("2025-01-15")  # 5.1.0 is later and 6.0.0-beta.1 is not stable
        self.assertEqual((i["latest"], i["libyear"], i["deprecated"], i["after_as_of"]), ("5.0.1", 2.0, "Use 5", False))
        self.assertEqual(self.dependency("2026-01-01")["latest"], "5.1.0")
        late = self.dependency("2022-01-01")  # the app uses a version published after the reference date
        self.assertEqual((late["after_as_of"], late["libyear"]), (True, None))

    def osv(self, as_of):
        from evaluator.collectors import osv
        recs = {"GHSA-old": {"id": "GHSA-old", "published": "2023-01-01T00:00:00Z", "database_specific": {"severity": "HIGH"}},
                "GHSA-new": {"id": "GHSA-new", "published": "2025-06-01T00:00:00Z", "database_specific": {"severity": "CRITICAL"}},
                "GHSA-gone": {"id": "GHSA-gone", "published": "2023-01-01T00:00:00Z", "withdrawn": "2024-01-01T00:00:00Z", "database_specific": {"severity": "HIGH"}},
                "MAL-1": {"id": "MAL-1", "published": "2023-01-01T00:00:00Z"},
                "GHSA-none": {"id": "GHSA-none", "published": "2023-01-01T00:00:00Z"},
                # dated with its CVE (before as_of) but reviewed into GitHub's database, the one npm audit reads, afterwards
                "GHSA-late": {"id": "GHSA-late", "published": "2024-10-19T18:32:12Z",
                              "database_specific": {"severity": "HIGH", "github_reviewed_at": "2025-03-01T15:56:42Z"}}}
        def post(url, body, timeout=60):
            return {"results": [{"vulns": [{"id": i} for i in recs]} if q["package"]["name"] == "qs" else {} for q in body["queries"]]}
        with mock.patch.object(osv, "post", side_effect=post), mock.patch.object(osv, "get", side_effect=lambda u: recs[u.rsplit("/", 1)[1]]):
            return osv.vulnerabilities([{"name": "qs", "version": "6.11.0", "dev": True}, {"name": "qs", "version": "6.11.0", "dev": False},
                                        {"name": "jest", "version": "29.7.0", "dev": True}], as_of)

    def test_osv_counts_the_advisories_in_force_at_the_reference_date(self):
        v = self.osv("2025-01-15")
        self.assertEqual((v["ok"], v["queried"], v["high"], v["critical"], v["unknown_severity"], v["published_after_as_of"]), (True, 2, 1, 1, 1, 2))
        self.assertEqual(sorted(x["id"] for x in v["items"]), ["GHSA-none", "GHSA-old", "MAL-1"])  # withdrawn and later ones left out
        self.assertFalse(v["items"][0]["dev"])  # also installed outside devDependencies: production
        self.assertEqual((self.osv("2025-12-31")["critical"]), 2)  # GHSA-new is in force by then
        self.assertEqual(self.osv("2025-12-31")["high"], 2)  # and GHSA-late, reviewed in March

    def test_osv_without_network(self):
        from evaluator.collectors import osv
        with mock.patch.object(osv, "post", side_effect=OSError("offline")):
            v = osv.vulnerabilities([{"name": "qs", "version": "1.0.0", "dev": False}], "2025-01-15")
        self.assertEqual((v["ok"], v["error"]), (False, "offline"))

    def technologies(self, items, **pk):
        m = {"packages": {"packages": [{"dir": ".", "dependencies": {}, "devDependencies": {}, "engines": {}}], "as_of": "2025-01-15",
                          "npm": {"ok": True, "items": items}, **pk}, "eol": {}, "postgres_images": []}
        return ev.eval_technologies(m, {}, Opts)

    @staticmethod
    def item(pkg, resolved, latest, libyear=0.0, **over):
        return {"pkg": pkg, "spec": "^1", "dir": ".", "dev": False, "resolved": resolved, "resolved_source": "lockfile", "latest": latest,
                "libyear": libyear, "deprecated": None, "after_as_of": False, **over}

    def test_c3_uses_the_resolved_version_and_c4_osv(self):
        items = [self.item("a", "2.1.0", "3.0.0", 1.5), self.item("b", "3.2.0", "3.4.0", 0.2), self.item("c", "1.0.0", "1.0.0", dev=True)]
        vulns = {"ok": True, "high": 1, "critical": 0, "items": [{"pkg": "qs", "version": "6.11.0", "id": "GHSA-x", "severity": "HIGH", "dev": False}],
                 "unknown_severity": 0, "published_after_as_of": 3, "queried": 40}
        crit, met, evid, finding, _ = self.technologies(items, vulnerabilities=vulns)
        self.assertEqual((crit["C3"]["value"], crit["C3"]["ok"]), ("1/3 = 33.3%", False))
        self.assertEqual((crit["C4"]["ok"], crit["C4"]["value"], crit["C4"]["source"]), (False, 1, "auto (OSV)"))
        self.assertEqual((met["libyear"]["dependencies"]["total"], met["libyear"]["dependencies"]["mean"]), (1.7, 0.85))
        self.assertEqual(met["advisories_published_after_as_of"], 3); self.assertIn("1.7 libyears", finding)

    def test_a_reference_date_earlier_than_the_app_leaves_c3_pending(self):
        crit, met, _, finding, _ = self.technologies([self.item("a", "2.0.0", "1.0.0", None, after_as_of=True)])
        self.assertIsNone(crit["C3"]["ok"]); self.assertEqual(met["newer_than_as_of"], ["a 2.0.0"]); self.assertIn("WARNING", finding)

    def test_an_older_metrics_json_is_still_scored(self):
        old = [{"pkg": "a", "spec": "^2.0.0", "base": "2.0.0", "latest": "3.1.0", "deprecated": None}]
        crit, *_ = self.technologies(old, audit={"ok": True, "high": 0, "critical": 2})
        self.assertEqual((crit["C3"]["ok"], crit["C4"]["value"]), (False, 2))
        self.assertIn("npm audit, older evaluation", crit["C4"]["source"])


class TestAscmmDensity(unittest.TestCase):
    """ISO/IEC 5055 occurrences of every detected weakness with their density per KLOC (Annex C.1), taken from the points' own results."""

    @staticmethod
    def point(pid, criteria=None, metrics=None, evaluable=True):
        return {"id": pid, "evaluable": evaluable, "metrics": metrics or {},
                "criteria": {k: {"ok": None, "value": v} for k, v in (criteria or {}).items()}}

    def model(self):
        fns = [{"file": "a.js", "line": 1, "name": "f", "test": False, "cc": 3, "loc": 10, "params": list("abcdefgh")}]
        return {"ast": {"files": [{"path": "a.js", "loc": 1500, "test": False}, {"path": "a.test.js", "loc": 900, "test": True}], "functions": fns}}

    def points(self, **over):
        pts = {"tests": self.point("tests", {"C1": {"switch_without_default": 2, "fallthrough": 0, "labeled_jumps": 1}}),
               "coupling": self.point("coupling", {"C1": 1, "C5": 3}),
               "cyclomatic": self.point("cyclomatic", metrics={"clones": 4, "functions_cc_above_threshold": 2}),
               "cohesion": self.point("cohesion", {"C4": 0}, {"functions_fanout_above": 5}),
               "configuration": self.point("configuration", {"C1": 2, "C2": {"a literal (a.js)": 3}}),
               "layers": self.point("layers", metrics={"violations": 0}),
               "hierarchies": self.point("hierarchies", {"C1": 0, "C2": 0, "C3": 0})}
        pts.update(over)
        return list(pts.values())

    def weakness(self, a, cwe):
        return next(w for w in a["weaknesses"] if w["cwe"] == cwe)

    def test_counts_come_from_the_points_and_are_normalized_by_production_kloc(self):
        from evaluator.ascmm import ascmm_profile
        a = ascmm_profile(self.model(), self.points())
        self.assertEqual(a["kloc"], 1.5)  # tests are not production code
        self.assertEqual(len(a["weaknesses"]), 15 + 6)  # CWE-570/571 are one indicator
        self.assertEqual((self.weakness(a, "CWE-478")["count"], self.weakness(a, "CWE-478")["per_kloc"]), (2, 1.333))
        self.assertEqual(self.weakness(a, "CWE-1052")["count"], 1)  # distinct literals S1192 reported
        self.assertEqual((a["scored"]["occurrences"], a["scored"]["per_kloc"], a["scored"]["complete"]), (21, 14.0, True))
        self.assertEqual(self.weakness(a, "CWE-1064")["count"], 1)  # informational, from the AST
        self.assertFalse(a["all"]["complete"]); self.assertIn("CWE-480", a["all"]["not_measured"])  # no ESLint result

    def test_a_count_that_was_not_measured_makes_the_total_a_lower_bound(self):
        from evaluator.ascmm import ascmm_comparison_md, ascmm_markdown, ascmm_profile
        a = ascmm_profile(self.model(), self.points(coupling=self.point("coupling", {"C1": 1, "C5": None}),
                                                     hierarchies=self.point("hierarchies", evaluable=False)))
        self.assertIsNone(self.weakness(a, "CWE-561")["count"]); self.assertIsNone(self.weakness(a, "CWE-1074")["count"])
        self.assertEqual(a["scored"]["not_measured"], ["CWE-561", "CWE-1062", "CWE-1074", "CWE-1086"])
        md = "\n".join(ascmm_markdown(a))
        self.assertIn("**ASCMM, scored weaknesses:** ≥ 18 (≥ 12.0/KLOC)", md)
        cmp_md = "\n".join(ascmm_comparison_md([("claude-n1-r1", {"ascmm": a}), ("old-run", {})]))
        self.assertIn("| claude-n1-r1 | 1.5 | ≥ 18 | ≥ 12.0 |", cmp_md); self.assertNotIn("old-run", cmp_md)

    def test_comparison_columns(self):
        from evaluator.ascmm import COLUMNS, ascmm_columns, ascmm_profile
        prof = {"ascmm": ascmm_profile(self.model(), self.points())}
        self.assertEqual(dict(zip(COLUMNS, ascmm_columns(prof)))["ascmm_scored_per_kloc"], 14.0)
        self.assertEqual(ascmm_columns({}), [None] * len(COLUMNS))  # a profile written before this measure


class TestContractConformance(unittest.TestCase):
    """Runtime conformance to the OpenAPI contract with Prism as a validating proxy (contract_conformance.py, acceptance_check.py --app)."""

    APP = FIX / "conformance_app"

    def test_violations_are_classified_and_invalid_requests_do_not_count(self):
        import contract_conformance as cc
        calls = [{"method": "GET", "path": "/api/products", "status": 200, "violations": [{"location": ["response", "body", "0", "id"], "severity": "Error", "message": "must be integer"}]},
                 {"method": "GET", "path": "/api/health", "status": 200, "violations": [{"location": ["request"], "severity": "Warning", "message": "Selected route not found"}]},
                 {"method": "GET", "path": "/api/orders/1", "status": 418, "violations": [{"location": ["response"], "message": "Unable to match the returned status code with those defined in the document: 200, 404"}]},
                 {"method": "POST", "path": "/api/orders", "status": 400, "violations": [{"location": ["request", "body", "qty"], "severity": "Error", "message": "must be integer"}]},
                 {"method": "POST", "path": "/api/orders", "status": 201, "violations": []}]
        r = cc.summarize(calls, "docs/openapi.yaml", "/api")
        self.assertEqual((r["calls"], r["conforming"], r["conformance_pct"], r["invalid_requests"]), (5, 2, 40.0, 1))
        self.assertEqual([len(r[k]) for k in ("undocumented_routes", "undocumented_status", "invalid_responses")], [1, 1, 1])

    def test_the_suite_runs_direct_when_the_app_has_no_contract(self):
        with mock.patch.object(acceptance_check, "run", return_value={"passed": 1, "total": 1}) as run:
            r = acceptance_check.run_with_contract("http://127.0.0.1:1", "ecommerce", str(FIX / "lint_app"))
        run.assert_called_once_with("http://127.0.0.1:1", "ecommerce")
        self.assertEqual((r["_conformance"]["ok"], r["_conformance"]["error"]), (False, "the app has no OpenAPI contract"))

    def test_through_prism_against_a_live_api(self):
        import contract_conformance as cc
        if not cc.available():
            self.skipTest("Prism is not installed (npm install)")
        port = cc.free_port()
        srv = subprocess.Popen(["node", str(self.APP / "server.js"), str(port)])
        try:
            for _ in range(50):
                try:
                    socket.create_connection(("127.0.0.1", port), timeout=1).close(); break
                except OSError:
                    time.sleep(0.1)
            def suite(base, domain):  # stands in for the domain suite: the calls the gate would make
                for m, p, b in (("GET", "/api/products", None), ("GET", "/api/health", None), ("GET", "/api/orders/1", None),
                                ("POST", "/api/orders", {"qty": "many"}), ("POST", "/api/orders", {"qty": 2})):
                    acceptance_check.call(base, m, p, b)
                return {"base": base, "total": 1, "passed": 1}
            with mock.patch.object(acceptance_check, "run", side_effect=suite):
                r = acceptance_check.run_with_contract(f"http://127.0.0.1:{port}", "ecommerce", str(self.APP))
        finally:
            srv.terminate(); srv.wait(timeout=10)
        c = r["_conformance"]
        self.assertTrue(c["ok"], c); self.assertEqual(c["base_path"], "/api")  # the relative servers[].url was applied for Prism
        self.assertEqual(r["base"], f"http://127.0.0.1:{port}")  # acceptance.json keeps the real backend, not the proxy
        self.assertEqual((c["calls"], c["conforming"], c["invalid_requests"]), (5, 2, 1))
        self.assertTrue(c["invalid_responses"][0].startswith("GET /api/products → 200"), c["invalid_responses"])
        self.assertIsNone(acceptance_check.CALLS)  # recording is switched off again

    def test_the_contracts_point_reports_it_without_changing_the_level(self):
        from evaluator.points.contracts import runtime_conformance
        rc = {"ok": True, "conformance_pct": 40.0, "calls": 5, "undocumented_routes": ["GET /api/health → 200: x"], "undocumented_status": [],
              "invalid_responses": ["GET /api/products → 200: y"]}
        met, ev, txt = runtime_conformance({"conformance": rc})
        self.assertEqual((met["runtime_conformance_pct"], met["invalid_responses"]), (40.0, 1)); self.assertIn("40.0% of the responses", txt)
        self.assertEqual(runtime_conformance({}), ({}, [], ""))
        self.assertIn("not measured", runtime_conformance({"conformance": {"ok": False, "error": "no contract"}})[2])

    def test_the_latest_versioned_contract_is_evaluated(self):
        from evaluator.collectors.contract import contract_rank
        self.assertEqual(sorted(["backend/openapi.yaml", "docs/openapi.yaml", "docs/R2/openapi.yaml"], key=contract_rank)[0], "docs/R2/openapi.yaml")


class TestMutation(unittest.TestCase):
    """Mutation testing with StrykerJS (evaluator/collectors/mutation.py): informational, only with --mutation and --run-tests."""

    def test_score_counts_only_valid_mutants(self):
        from evaluator.collectors.mutation import score
        self.assertEqual(score({"Killed": 6, "Timeout": 1, "Survived": 2, "NoCoverage": 1, "CompileError": 5, "Ignored": 3}), 70.0)
        self.assertIsNone(score({"CompileError": 2}))

    def test_only_production_sources_of_the_package_are_mutated(self):
        from evaluator.collectors.mutation import mutate_files
        with tempfile.TemporaryDirectory() as t:
            app = Path(t); be = app / "backend"; nested = be / "tools"
            ast = {"files": [{"path": p, "test": p.endswith(".test.js")} for p in
                             ("backend/src/a.js", "backend/src/a.test.js", "backend/jest.config.js", "backend/migrations/1-init.js",
                              "backend/tools/x.js", "frontend/src/App.jsx")]}
            self.assertEqual(mutate_files(app, be, ast, [nested]), ["src/a.js"])

    def test_the_tests_point_reports_it_without_changing_the_level(self):
        from evaluator.points.tests import mutation_measure
        mu = {"ok": True, "tool": "StrykerJS 10.1.1 (command runner)", "score": 58.3, "statuses": {"Killed": 7, "Survived": 5},
              "packages": [{"ok": True, "survivors": ["src/price.js:11 EqualityOperator (Survived)"]}]}
        met, ev, txt = mutation_measure({"mutation": mu})
        self.assertEqual((met["mutation_score"], met["mutants_detected"], met["mutants_undetected"]), (58.3, 7, 5))
        self.assertIn("7 of 12 valid mutants", txt); self.assertTrue(ev[0].startswith("surviving mutant: src/price.js:11"))
        self.assertEqual(mutation_measure({}), ({}, [], ""))

    def test_stryker_on_a_node_test_suite(self):
        from evaluator.collectors import mutation
        if not mutation.available():
            self.skipTest("StrykerJS is not installed (npm install)")
        with tempfile.TemporaryDirectory() as t:
            app = Path(t) / "app"; shutil.copytree(FIX / "mutation_app", app); out = Path(t) / "out"; out.mkdir()
            ast = ev.run_ast(app, out)
            before = sorted(p.relative_to(app).as_posix() for p in app.rglob("*"))
            r = mutation.run_mutation(app, [{"dir": "backend", "scripts": {"test": "node --test"}}], ast, out)
            after = sorted(p.relative_to(app).as_posix() for p in app.rglob("*"))
        self.assertTrue(r["ok"], r); self.assertEqual(before, after)  # the app is not modified (Stryker works in a sandbox copy)
        # unitPrice is tested, shipping is not: every surviving mutant is in shipping (lines 10-11)
        self.assertTrue(0 < r["score"] < 100, r["score"])
        self.assertTrue(all(re.search(r"src/price\.js:1[01] ", s) for s in r["packages"][0]["survivors"]), r["packages"][0]["survivors"])


import pg_temp  # noqa: E402
from evaluator.points import cohesion as _cohesion  # noqa: E402


class TestJudgeEvidencePriority(unittest.TestCase):
    """The evidence is assembled by priority and says when it is incomplete; the criteria of a point are asked together."""

    def test_essential_parts_go_whole_and_what_is_cut_is_listed(self):
        text = judge.assemble([("### schema\n" + "x" * 500, True), ("### README\n" + "r" * 800, False), ("### routes\n" + "y" * 50, False)], limit=900)
        self.assertIn("x" * 500, text)  # essential, whole
        self.assertIn("THE EVIDENCE IS INCOMPLETE", text); self.assertIn("### README (cut)", text); self.assertIn("### routes (left out)", text)
        self.assertNotIn("INCOMPLETE", judge.assemble([("a", True), ("b", False)], limit=100))

    def test_data_model_evidence_shows_long_schema_files_whole_and_the_design_documents(self):
        with tempfile.TemporaryDirectory() as t:
            app, res = Path(t) / "app", Path(t) / "res"; (app / "docs" / "R2").mkdir(parents=True); res.mkdir()
            (res / "metrics.json").write_text("{}", encoding="utf-8")
            (app / "schema.sql").write_text("\n".join(f"-- line {i}" for i in range(150)) + "\nCREATE TABLE last_one (id INT);", encoding="utf-8")
            (app / "docs" / "R2" / "README.md").write_text("orders.coupon_code is a snapshot of the code at checkout.", encoding="utf-8")
            (app / "docs" / "R2" / "deploy.md").write_text("How to deploy.", encoding="utf-8")
            m = {"app": str(app), "readme": "", "er": {"found": False, "text": ""}, "ast": {"queryFields": [], "routes": []},
                 "schema": {"tables": {"last_one": {"file": "schema.sql:151", "source": "sql", "columns": {}, "primary_key": [], "foreign_keys": [],
                                                     "unique": [], "checks": [], "indexes": []}}}}
            text = judge.evidence("data_model", ["C2", "C5"], res, m, {"finding": "f", "evidence": []})
        self.assertIn("CREATE TABLE last_one", text)  # beyond the 90 lines the evidence used to show
        self.assertIn("coupon_code is a snapshot", text); self.assertNotIn("How to deploy", text)

    def test_one_prompt_per_point_with_a_shared_justification_policy(self):
        p = judge.build_prompt("data_model", ["C2", "C5"], {"C2": "normalized", "C5": "no redundancy"}, "EV")
        self.assertIn("data_model.C2: normalized", p); self.assertIn("data_model.C5: no redundancy", p)
        self.assertIn("judge it the same way in all of them", p); self.assertIn('"C2": {"ok"', p); self.assertIn('"C5": {"ok"', p)
        self.assertEqual(p.count(judge.JUSTIFIED), 2)  # C2 and C5 decide "justified" with the same words
        self.assertIn("answer null", p)

    def test_parse_reads_one_vote_per_criterion(self):
        r = judge.parse('ok: {"C2": {"ok": false, "justification": "a.sql:3", "confidence": "high"}, "C5": {"ok": true}}', ["C2", "C5"])
        self.assertEqual((r["C2"]["ok"], r["C2"]["confidence"], r["C5"]["ok"]), (False, "high", True))
        self.assertIsNone(judge.parse('{"C2": {"ok": true}}', ["C2", "C5"])["C5"])
        self.assertTrue(judge.parse('{"ok": true}', ["C3"])["C3"]["ok"])  # a flat vote when a single criterion was asked
        self.assertIsNone(judge.parse("no json", ["C3"]))

    def test_main_asks_the_criteria_of_a_point_in_one_prompt(self):
        prompts = []

        def fake_query(cmd, prompt, timeout):
            prompts.append(prompt)
            return 0, '{"C2": {"ok": false, "justification": "j"}, "C5": {"ok": true, "justification": "k"}}', ""
        point = {"id": "data_model", "finding": "f", "evidence": [], "criteria": {"C2": {"desc": "two"}, "C5": {"desc": "five"}}}
        with tempfile.TemporaryDirectory() as t:
            res = Path(t)
            (res / "meta.json").write_text(json.dumps({"model": "gpt-x"}), encoding="utf-8")
            (res / "metrics.json").write_text(json.dumps({"app": t}), encoding="utf-8")
            with mock.patch.object(judge, "pending", return_value=[(point, "C2"), (point, "C5")]), mock.patch.object(judge, "evidence", return_value="EV"), \
                    mock.patch.object(judge, "query", side_effect=fake_query), mock.patch.object(sys, "argv", ["judge.py", t, "--model", "claude-opus-5-5"]):
                judge.main()
            out = json.loads((res / "judge.json").read_text(encoding="utf-8"))
        self.assertEqual(len(prompts), 3)  # 3 votes, one prompt each for both criteria
        self.assertEqual((out["decisions"]["data_model"]["C2"]["ok"], out["decisions"]["data_model"]["C5"]["ok"]), (False, True))

    def test_the_default_command_finds_the_cli_bundled_with_the_editor(self):
        name = "claude.exe" if os.name == "nt" else "claude"
        with tempfile.TemporaryDirectory() as t:
            for v in ("2.1.9", "2.1.10"):
                d = Path(t) / ".vscode" / "extensions" / f"anthropic.claude-code-{v}-x" / "resources" / "native-binary"; d.mkdir(parents=True)
                (d / name).write_text("", encoding="utf-8")
            with mock.patch.object(judge.shutil, "which", return_value=None), mock.patch.object(judge.Path, "home", return_value=Path(t)):
                cmd = judge.judge_command(judge.DEFAULT_CMD, "claude-opus-5-5")
        self.assertIn("claude-code-2.1.10-x", cmd[0]); self.assertEqual(cmd[1:], ["-p", "--model", "claude-opus-5-5"])
        self.assertEqual(judge.judge_command("my-judge {model}", "m"), ["my-judge", "m"])  # a custom command is left alone
        # a quoted Windows path reaches the OS without its quotes (shlex posix=False keeps them, and CreateProcess then fails)
        self.assertEqual(judge.judge_command(r'"C:\Program Files\nodejs\node.exe" j.mjs --model {model}', "m"),
                         [r"C:\Program Files\nodejs\node.exe", "j.mjs", "--model", "m"])


class TestDataModelPolymorphicAndTypes(unittest.TestCase):
    def test_a_polymorphic_reference_is_not_an_implicit_relation(self):
        sql = ("CREATE TABLE users (id SERIAL PRIMARY KEY, email TEXT NOT NULL UNIQUE);\n"
               "CREATE TABLE audit_log (id SERIAL PRIMARY KEY, entity TEXT NOT NULL, entity_id INTEGER NOT NULL, user_id INTEGER REFERENCES users(id));")
        s = rs.extract([("s.sql", sql)], {}, RUBRIC_REL)
        self.assertEqual(ra.polymorphic_references(s), ["audit_log.entity_id"]); self.assertEqual(ra.implicit_relations(s, RUBRIC_REL), [])
        c = ev.eval_data_model(dm_model(sql), {}, Opts())[0]["C1"]
        self.assertTrue(c["ok"]); self.assertEqual(c["value"]["polymorphic_references"], ["audit_log.entity_id"])

    def test_a_reference_to_an_existing_table_stays_implicit_even_with_a_type_column(self):
        sql = ("CREATE TABLE products (id SERIAL PRIMARY KEY);\n"
               "CREATE TABLE lines (id SERIAL PRIMARY KEY, product_id INTEGER NOT NULL, product_type TEXT);")
        s = rs.extract([("s.sql", sql)], {}, RUBRIC_REL)
        self.assertEqual(ra.polymorphic_references(s), []); self.assertEqual(ra.implicit_relations(s, RUBRIC_REL), ["lines.product_id"])

    def test_inconsistent_types_decide_c5_and_otherwise_it_stays_a_suggestion(self):
        bad = "CREATE TABLE a (id SERIAL PRIMARY KEY, code VARCHAR(10) NOT NULL);\nCREATE TABLE b (id SERIAL PRIMARY KEY, code INTEGER NOT NULL);"
        c5 = ev.eval_data_model(dm_model(bad), {}, Opts())[0]["C5"]
        self.assertFalse(c5["ok"]); self.assertTrue(c5["value"]["type_conflicts"]); self.assertTrue(c5["source"].startswith("auto"))
        self.assertIsNone(ev.eval_data_model(dm_model(OK_SQL, ER_MATCH, GOOD_QUERIES), {}, Opts())[0]["C5"]["ok"])

    def test_a_copy_justified_in_a_design_document_counts_as_justified(self):
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / "docs" / "R2").mkdir(parents=True)
            (Path(t) / "docs" / "R2" / "README.md").write_text("`orders.coupon_code` is an immutable snapshot taken at checkout.", encoding="utf-8")
            sql = ("CREATE TABLE coupons (id SERIAL PRIMARY KEY, code VARCHAR(20) NOT NULL UNIQUE);\n"
                   "CREATE TABLE orders (id SERIAL PRIMARY KEY, coupon_id INTEGER REFERENCES coupons(id), coupon_code VARCHAR(20));")
            m = dm_model(sql); m["app"] = t
            copies = ev.eval_data_model(m, {}, Opts())[0]["C2"]["value"]["denormalized_copies"]
        self.assertEqual(copies, [{"copy": "orders.coupon_code", "of": "coupons.code", "justified": True}])


class TestCohesionMeasuredFindings(unittest.TestCase):
    def cohesion(self, **ast):
        base = {"functions": [{"file": "a.js", "line": 1, "name": "f", "fanout": 0, "test": False}], "files": [{"path": "a.js", "loc": 50, "test": False}],
                "classes": [], "routes": [], "sqlStrings": [], "queryFields": [], "components": []}
        return ev.eval_cohesion({"ast": {**base, **ast}, "graph": {"modules": [], "cycles": []}}, {"dv8": {"DL": 0.9}}, Opts)[0]["C3"]

    def test_routes_and_queries_in_the_same_module_fail_c3(self):
        c3 = self.cohesion(routes=[{"file": "app.js", "line": 3, "method": "GET", "path": "/x"}],
                           sqlStrings=[{"file": "app.js", "line": 4, "text": "SELECT 1", "migration": False}])
        self.assertFalse(c3["ok"]); self.assertEqual(c3["value"]["routes_and_queries_in_one_file"], ["app.js"])

    def test_routes_with_queries_in_a_repository_or_only_in_migrations_stay_a_suggestion(self):
        c3 = self.cohesion(routes=[{"file": "http/app.js", "line": 3, "method": "GET", "path": "/x"}],
                           sqlStrings=[{"file": "data/repo.js", "line": 4, "text": "SELECT 1", "migration": False},
                                       {"file": "http/app.js", "line": 9, "text": "CREATE TABLE t (id INT)", "migration": True}])
        self.assertIsNone(c3["ok"])

    def test_a_component_over_the_threshold_fails_c3(self):
        limit = ev.RUBRIC["thresholds"]["cohesion"]["component_loc_max"]
        c3 = self.cohesion(components=[{"file": "App.jsx", "line": 8, "name": "App", "loc": limit + 1, "props": 0},
                                        {"file": "Row.jsx", "line": 1, "name": "Row", "loc": limit, "props": 2}])
        self.assertFalse(c3["ok"]); self.assertEqual(c3["value"][f"components_over_{limit}_loc"], [f"App.jsx:8 App ({limit + 1} LOC)"])
        self.assertEqual(_cohesion.oversized_components({"components": []}, limit), [])


class TestLayersSharedCore(unittest.TestCase):
    def layers(self, core_deps):
        layers = {"p/c.js": "presentation", "s/svc.js": "business", "d/repo.js": "data", "domain/errors.js": "business"}
        origin = {"p/c.js": "controllers", "s/svc.js": "services", "d/repo.js": "data", "domain/errors.js": "domain"}
        mods = [module("p/c.js", ["s/svc.js"] * 9), module("s/svc.js", ["d/repo.js"]), module("d/repo.js", ["domain/errors.js"]),
                module("domain/errors.js", core_deps)]
        return ev.eval_layers({"layers": layers, "layers_origin": origin, "graph": {"modules": mods}}, {}, Opts)

    def test_a_dependency_on_a_domain_module_without_outer_dependencies_is_not_a_violation(self):
        _, met, _, finding, forced = self.layers([])
        self.assertEqual(forced, ("Meets",) * 3); self.assertEqual(met["violations"], 0)
        self.assertEqual(met["shared_core_dependencies"], ["d/repo.js (data) → domain/errors.js (shared core)"]); self.assertIn("shared core", finding)

    def test_a_domain_module_that_reaches_the_data_layer_stays_doubtful(self):
        _, met, _, _, forced = self.layers(["d/repo.js"])
        self.assertEqual(met["doubtful_violations"], 1); self.assertIsNone(forced[0])


class TestPgTemp(unittest.TestCase):
    def test_find_bin_uses_pg_bin(self):
        exe = ".exe" if os.name == "nt" else ""
        with tempfile.TemporaryDirectory() as t:
            for b in ("initdb", "pg_ctl"):
                (Path(t) / f"{b}{exe}").write_text("", encoding="utf-8")
            with mock.patch.dict(os.environ, {"PG_BIN": t}):
                self.assertEqual(pg_temp.find_bin(), Path(t))

    def test_without_binaries_the_server_is_none(self):
        with mock.patch.object(pg_temp, "find_bin", return_value=None), pg_temp.server() as url:
            self.assertIsNone(url)

    @unittest.skipUnless(pg_temp.find_bin(), "no PostgreSQL server binaries")
    def test_a_real_temporary_server_accepts_connections_and_is_deleted(self):
        before = set(Path(tempfile.gettempdir()).glob("eval-pg-*"))
        with pg_temp.server() as url:
            self.assertRegex(url, r"^postgres://evaluator:[\w-]+@127\.0\.0\.1:\d+/postgres$")
            port = int(url.rsplit(":", 1)[1].split("/")[0])
            with socket.create_connection(("127.0.0.1", port), timeout=5):
                pass
            created = set(Path(tempfile.gettempdir()).glob("eval-pg-*")) - before
            self.assertEqual(len(created), 1)
        self.assertFalse(next(iter(created)).exists())


class TestBackendSecrets(unittest.TestCase):
    def test_random_secrets_for_jwt_and_the_secrets_of_env_example_only(self):
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / ".env.example").write_text("PORT=3001\nexport SESSION_SECRET=x\nJWT_SECRET=short\nREPLICA_DATABASE_URL=postgres://r@h/db\n", encoding="utf-8")
            s = pg_runtime.backend_secrets(t, {"PORT": "1"})
            self.assertEqual(sorted(s), ["JWT_SECRET", "SESSION_SECRET"]); self.assertTrue(all(len(v) >= 32 for v in s.values()))
            self.assertNotIn("JWT_SECRET", pg_runtime.backend_secrets(t, {"JWT_SECRET": "given-by-the-user"}))
        self.assertEqual(list(pg_runtime.backend_secrets(Path(t) / "missing")), ["JWT_SECRET"])


class TestCliTemporaryPostgres(unittest.TestCase):
    def test_postgres_without_admin_url_uses_a_temporary_server_for_the_batch(self):
        seen = []

        @contextlib.contextmanager
        def fake_server():
            yield "postgres://evaluator:pw@127.0.0.1:5999/postgres"

        def fake_evaluate(app, o_, dv8):
            seen.append(cli.UTF8.get("PG_ADMIN_URL"))
            return "r", "ok"
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / "codex-n1").mkdir()
            o = {"apps": [str(Path(t) / "codex-n1")], "apps_dir": t, "results": str(Path(t) / "res"), "model": "m", "allow_missing_model": False,
                 "skip_dv8": True, "rescore_only": False, "postgres": True}
            env = {k: v for k, v in os.environ.items() if k != "PG_ADMIN_URL"}
            with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(cli, "options", return_value=o), \
                    mock.patch.object(cli, "record_environment"), mock.patch.object(cli.pg_temp, "server", fake_server), \
                    mock.patch.object(cli, "evaluate_app", side_effect=fake_evaluate), \
                    mock.patch.object(cli, "execute", return_value=(0, "")), mock.patch.object(cli, "write_report", return_value="report.md"), \
                    contextlib.redirect_stdout(io.StringIO()) as out:
                cli.UTF8.pop("PG_ADMIN_URL", None)
                self.assertEqual(cli.cmd_evaluate(argparse.Namespace()), 0)
        self.assertEqual(seen, ["postgres://evaluator:pw@127.0.0.1:5999/postgres"])
        self.assertNotIn("PG_ADMIN_URL", cli.UTF8)  # nothing after the batch points at the stopped server
        self.assertIn("temporary server on 127.0.0.1:5999", out.getvalue())
