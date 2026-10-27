"""Tests of the evaluator itself (no external dependencies):  python -m unittest discover -s tests -v

They cover the rules that weigh most on the results: level from criteria, rule S1192, layers (with doubtful classification and with no
inter-layer dependencies), reading node:test coverage, the DV8 matrix and Unhealthy Inheritance.
"""
import json, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import evaluate as ev  # noqa: E402
import dv8_metrics  # noqa: E402
import judge  # noqa: E402
import cli  # noqa: E402


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
                     "components": [], "hooks": [], "security": {"evalCalls": [{"file": "a.js", "line": 3}], "secrets": [], "nosqlInjection": []},
                     "schemas": [{"fieldTypes": {"name": "String", "qty": "Number"}}]}}
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

    def test_data_model_detects_conflicting_types(self):
        sch = lambda n, qty: {"file": "m.js", "line": 1, "name": n, "fields": 3, "required": 1, "validated": 0, "refs": 0, "embedded": 0,
                              "indexedFields": 0, "schemaIndexCalls": 0, "fieldTypes": {"name": "String", "qty": qty, "x": "Date"}}
        m = {"ast": {"schemas": [sch("a", "Number"), sch("b", "String")], "populateCalls": []}}
        crit = ev.eval_data_model(m, {}, Opts())[0]
        self.assertIsNone(crit["C5"]["ok"]); self.assertEqual(crit["C5"]["suggested"], False)
        self.assertEqual(len(crit["C5"]["value"]["conflicts"]), 1)

    @staticmethod
    def _model(**mongo):
        sch = lambda n: {"file": "m.js", "line": 1, "name": n, "fields": 4, "required": 3, "validated": 1, "refs": 0, "embedded": 0,
                         "indexedFields": 0, "schemaIndexCalls": 0, "fieldTypes": {}}
        col = lambda objectid, indexes: {"objectid": objectid, "indexes": [{"name": "_id_", "key": {"_id": 1}}] + indexes,
                                         "fields": [], "mixed_type_fields": [], "arrays": [], "size_bytes": {"max": 500}}
        ix = lambda field: {"name": field + "_1", "key": {field: 1}}
        cols = {"orders": col(["userId"], [ix("userId")]), "users": col([], [ix("email")])}
        cols.update(mongo.get("cols", {}))
        return {"ast": {"schemas": [sch("Order"), sch("User")], "populateCalls": [], "queryFields": mongo.get("q", [])},
                "mongo": {"collections": cols, "relations": mongo.get("rel", [])}}

    def test_c4_with_real_database_requires_index_on_queried_fields(self):
        q = lambda fields: {"file": "s.js", "line": 3, "model": "Order", "call": "find", "fields": fields, "sort": [], "inLoop": False}
        ok = ev.eval_data_model(self._model(q=[q(["userId"])]), {}, Opts())[0]["C4"]
        self.assertTrue(ok["ok"]); self.assertEqual(ok["source"], "auto (live database)")
        with_id = ev.eval_data_model(self._model(q=[q(["_id", "status"])]), {}, Opts())[0]["C4"]
        self.assertTrue(with_id["ok"])  # filters by _id: covered by the _id index
        bad = ev.eval_data_model(self._model(q=[q(["userId"]), q(["status"])]), {}, Opts())[0]["C4"]
        self.assertFalse(bad["ok"]); self.assertEqual(bad["value"]["unindexed_queries_pct"], 50.0)
        no_rel = ev.eval_data_model(self._model(cols={"orders": {"objectid": ["userId"], "indexes": [{"name": "_id_", "key": {"_id": 1}}, {"name": "x", "key": {"x": 1}}],
                                                                 "fields": [], "mixed_type_fields": [], "arrays": [], "size_bytes": None}}), {}, Opts())[0]["C4"]
        self.assertFalse(no_rel["ok"])

    def test_c1_detects_implicit_relations_from_the_data(self):
        rel = {"collection": "orders", "field": "userId", "type": "String", "target": "users", "distinct": 5, "match": 1.0, "orphans": 0.0}
        c1 = ev.eval_data_model(self._model(rel=[rel]), {}, Opts())[0]["C1"]
        self.assertFalse(c1["ok"]); self.assertEqual(c1["value"]["implicit_relations"], ["orders.userId → users"])
        declared = dict(rel, type="ObjectId", orphans=0.2, match=0.8)
        c1 = ev.eval_data_model(self._model(rel=[declared]), {}, Opts())[0]["C1"]
        self.assertTrue(c1["ok"]); self.assertEqual(len(c1["value"]["orphans"]), 1)

    def test_data_model_helpers(self):
        self.assertEqual(ev.collection_of("Order", ["orders", "users"]), "orders")
        self.assertEqual(ev.collection_of("Category", ["categories"]), "categories")
        self.assertIsNone(ev.collection_of("productRepository", ["products"]))
        self.assertEqual(len(ev.mixed_naming_convention({"unit_price", "createdAt", "_id"})), 1)
        self.assertEqual(ev.mixed_naming_convention({"createdAt", "userId"}), [])


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
    m = {"readme": "", "env_example": False, "contract": {"files": []},
         "ast": {"files": [{"path": "a.js", "test": False}], "schemas": [{"name": "A"}]},
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
        m = artifact_model(ast={"files": [{"path": "a.js", "test": False}], "schemas": []}, readme="")
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
