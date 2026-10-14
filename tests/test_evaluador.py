"""Pruebas del propio evaluador (sin dependencias externas):  python -m unittest discover -s tests -v

Cubren las reglas que más pesan en los resultados: nivel por criterios, regla S1192, capas (con clasificación dudosa y sin
dependencias entre capas), lectura de cobertura de node:test, matriz DV8 y Unhealthy Inheritance.
"""
import json, sys, tempfile, unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
import evaluate as ev  # noqa: E402
import dv8_metrics  # noqa: E402
import eval as cli  # noqa: E402


class Opts:
    aceptar_heuristicas = False


def crit(**c):
    return {k: {"ok": v} for k, v in c.items()}


class TestNivel(unittest.TestCase):
    def test_todos_cumplen(self):
        self.assertEqual(ev.level_from(crit(C1=True, C2=True)), ("Cumple", "Cumple", "Cumple"))

    def test_mitad_es_parcial_y_menos_no_cumple(self):
        self.assertEqual(ev.level_from(crit(C1=True, C2=False))[0], "Parcial")
        self.assertEqual(ev.level_from(crit(C1=True, C2=False, C3=False))[0], "No cumple")

    def test_pendiente_da_rango(self):
        nivel, lo, hi = ev.level_from(crit(C1=True, C2=None, C3=None))
        self.assertIsNone(nivel); self.assertEqual((lo, hi), ("No cumple", "Cumple"))

    def test_criterio_obligatorio(self):
        self.assertEqual(ev.level_from(crit(C1=False, C2=True, C3=True), must=("C1",))[0], "No cumple")


class TestConfiguracionS1192(unittest.TestCase):
    def evaluar(self, occ):
        m = {"ast": {"networkLiterals": [], "files": [{"path": "a.js", "loc": 1000, "test": False}], "literalOccurrences": occ,
                     "envFiles": {"backend/src/config.js": 1}}, "env_example": True}
        return ev.eval_configuracion(m, {}, {}, Opts)[0]["C2"]

    def test_marca_literal_largo_repetido_tres_veces(self):
        c = self.evaluar({"Ruta no encontrada del servidor": ["a:1", "a:2", "a:3"]})
        self.assertFalse(c["ok"]); self.assertEqual(c["valor"], {"Ruta no encontrada del servidor": 3})

    def test_no_marca_palabras_solas_ni_ignorados_ni_dos_repeticiones(self):
        c = self.evaluar({"despachado": ["a:1"] * 5, "application/json": ["a:1"] * 4, "Texto largo de ejemplo": ["a:1", "a:2"]})
        self.assertTrue(c["ok"])


def modulo(src, destinos):
    return {"source": src, "deps": [{"to": d, "local": True} for d in destinos]}


class TestCapas(unittest.TestCase):
    def m(self, modulos, layers, origen=None):
        return {"layers": layers, "layers_origen": origen or {}, "graph": {"modules": modulos}}

    def test_sin_dependencias_entre_capas_queda_pendiente(self):
        m = self.m([], {"a/controllers/x.js": "presentacion", "a/services/y.js": "negocio"})
        crit_, _, _, _, forced = ev.eval_capas(m, {}, {}, Opts)
        self.assertIsNone(crit_["C2"]["ok"]); self.assertEqual(forced, (None, "No cumple", "Cumple"))

    def test_manual_resuelve_sin_dependencias(self):
        m = self.m([], {"a/controllers/x.js": "presentacion", "a/services/y.js": "negocio"})
        self.assertEqual(ev.eval_capas(m, {"capas": {"C2": {"ok": True}}}, {}, Opts)[4], ("Cumple",) * 3)
        self.assertEqual(ev.eval_capas(m, {"capas": {"C2": {"ok": False}}}, {}, Opts)[4], ("No cumple",) * 3)

    def _con_violacion(self, origen_fuente):
        layers = {"p/c.js": "presentacion", "n/s.js": "negocio", "d/m.js": "datos"}
        mods = [modulo("p/c.js", ["n/s.js"] * 9), modulo("d/m.js", ["n/s.js"])]  # 1 violación (datos→negocio) de 10
        return self.m(mods, layers, {"d/m.js": origen_fuente, "n/s.js": "services", "p/c.js": "controllers"})

    def test_violacion_con_directorio_ambiguo_queda_pendiente(self):
        m = self._con_violacion("domain")
        _, met, _, _, forced = ev.eval_capas(m, {}, {}, Opts)
        self.assertEqual(met["violaciones_dudosas"], 1); self.assertEqual(forced, (None, "No cumple", "Cumple"))
        self.assertEqual(ev.eval_capas(m, {"capas": {"C2": {"ok": True}}}, {}, Opts)[4], ("Cumple",) * 3)
        self.assertEqual(ev.eval_capas(m, {"capas": {"C2": {"ok": False}}}, {}, Opts)[4], ("No cumple",) * 3)

    def test_violacion_firme_no_cumple(self):
        self.assertEqual(ev.eval_capas(self._con_violacion("models"), {}, {}, Opts)[4], ("No cumple",) * 3)

    def test_sin_violaciones_cumple(self):
        m = self.m([modulo("p/c.js", ["n/s.js"] * 3), modulo("n/s.js", ["d/m.js"])],
                   {"p/c.js": "presentacion", "n/s.js": "negocio", "d/m.js": "datos"})
        self.assertEqual(ev.eval_capas(m, {}, {}, Opts)[4], ("Cumple",) * 3)


class TestCobertura(unittest.TestCase):
    def test_parse_lcov_suma_archivos_sin_cargar(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t); (d / "src").mkdir(); (d / "node_modules").mkdir()
            (d / "src" / "a.js").write_text("x\n" * 10); (d / "src" / "b.js").write_text("a\n\nb\nc\n")
            (d / "src" / "a.test.js").write_text("t\n"); (d / "node_modules" / "z.js").write_text("z\n")
            lcov = d / "lcov.info"
            lcov.write_text("SF:src/a.js\nLF:10\nLH:5\nBRF:4\nBRH:2\nend_of_record\n")
            r = ev.parse_lcov(lcov, d)
        self.assertEqual((r["lines_total"], r["lines_cov"], r["br_total"], r["br_cov"], r["unloaded"]), (13, 5, 4, 2, 1))


class TestDV8(unittest.TestCase):
    def test_matriz_desde_plantilla(self):
        plantilla = json.loads((RAIZ / "dv8" / "plantilla-matriz.json").read_text(encoding="utf-8"))
        graph = {"modules": [{"source": "b.js", "deps": [{"to": "a.js", "local": True}, {"to": "a.js", "local": True},
                                                          {"to": "express", "local": False}, {"to": "b.js", "local": True}]},
                             {"source": "a.js", "deps": []}]}
        matriz, tipo = dv8_metrics.construir_matriz(graph, plantilla, "x")
        self.assertEqual(matriz["variables"], ["a.js", "b.js"]); self.assertEqual(tipo, "Import")
        self.assertEqual(matriz["cells"], [{"src": 1, "dest": 0, "values": {"Import": 2.0}}])
        self.assertEqual(matriz["name"], "x")

    def _uih(self, clases):
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / "ast.json").write_text(json.dumps({"classes": clases}))
            return dv8_metrics.unhealthy_inheritance(Path(t))

    def test_unhealthy_inheritance(self):
        self.assertEqual(self._uih([{"name": "A", "extends": "Error"}, {"name": "B", "extends": "Error"}]), 0)
        self.assertEqual(self._uih([]), 0)
        self.assertIsNone(self._uih([{"name": "A", "extends": "Error"}, {"name": "B", "extends": "A"}]))


class TestCLI(unittest.TestCase):
    def test_identidad(self):
        self.assertEqual(cli.identidad("claude-n2"), ("claude", "N2"))
        self.assertEqual(cli.identidad("mi_app"), ("mi_app", "n/d"))


if __name__ == "__main__":
    unittest.main()
