# Marco de evaluación de mantenibilidad

Herramienta para medir la mantenibilidad de aplicaciones MERN (MongoDB, Express, React, Node) con **11 puntos de decisión**
agrupados en 4 subcaracterísticas (Testabilidad, Analizabilidad, Modularidad, Modificabilidad). Se diseñó para comparar
aplicaciones generadas por agentes de IA a partir de especificaciones con distinto nivel de detalle, pero evalúa
cualquier aplicación con la estructura `backend/` + `frontend/`.

Qué hace: lee el código, consulta el registro de npm, ejecuta las pruebas de la app, calcula métricas de acoplamiento con DV8
y arma un perfil con el puntaje de 0 a 100. Lo que no se puede decidir automáticamente queda **pendiente** y el resultado se
expresa como un **rango** hasta que una persona lo complete.

> **Seguridad.** Evaluar con pruebas (`--run-tests`, el comportamiento por defecto de `evaluar`) instala dependencias y
> ejecuta código generado por un modelo, que no es de confianza. Hágalo en una máquina virtual o contenedor desechable, o use
> `--sin-pruebas`.

## Requisitos

| Requisito | Notas |
|---|---|
| Python ≥ 3.9 | Solo biblioteca estándar: no hay `pip install`. |
| Node.js ≥ 18 y npm | Se usan para el análisis del código y las consultas a npm. |
| `npm install` en esta carpeta | Instala `ts-morph`, `dependency-cruiser`, `depcheck`, `spectral`. |
| DV8 (opcional) | Para DL y PC. Sin él esos criterios quedan pendientes. Defina `DV8_CONSOLE` si no está en la ruta por defecto. |
| Red (opcional) | Versiones y vulnerabilidades de npm. Sin red use `--offline`. |

```
npm install
python eval.py doctor        # comprueba todo lo anterior y dice qué falta
```

## Uso: tres pasos

**1. Crear las aplicaciones.** Una carpeta por aplicación dentro de `apps/`, con el nombre `<agente>-<nivel>`
(por ejemplo `apps/claude-n1`). Cada una debe tener `backend/` y `frontend/`. Las instrucciones para generarlas con un
agente, sin que un nivel contamine a otro, están en [docs/generar-aplicaciones.md](docs/generar-aplicaciones.md).

**2. Evaluar todo.**

```
python eval.py evaluar --modelo "<modelo que generó las apps>"
```

Por cada app evalúa los 11 puntos, ejecuta las pruebas, calcula DL y PC con DV8, deja las plantillas de revisión manual y
al final agrega los resultados. Opciones útiles: `--sin-pruebas`, `--sin-dv8`, `--offline`, `--aceptar-heuristicas`, o
indicar carpetas concretas (`python eval.py evaluar ruta/app1 ruta/app2`). Puede fijar las opciones en `experimento.json`
(copie [experimento.ejemplo.json](experimento.ejemplo.json)).

**3. Ver los resultados.** Abra `resultados/informe.md` (se regenera con `python eval.py informe`). Trae el resultado global,
la matriz de los 11 puntos, los pendientes de revisión manual, los hallazgos, las advertencias metodológicas y el entorno.
Hay un [ejemplo real](ejemplo/informe-ejemplo.md).

### Cerrar los rangos: la revisión manual

Mientras haya criterios que el programa no puede decidir, los puntajes son rangos. Por cada app, en
`resultados/<app>/`:

1. Lea `revision_manual.md`: enunciado de cada criterio pendiente, evidencia y una sugerencia.
2. Copie `revision_manual.borrador.json` a `revision_manual.json` y cambie `ok` por `true` o `false`.
3. Vuelva a ejecutar `python eval.py evaluar`. El archivo se lee solo.

Detalles en [docs/revision-manual.md](docs/revision-manual.md).

## Contenido del repositorio

| Ruta | Para qué sirve |
|---|---|
| `eval.py` | Punto de entrada: `doctor`, `evaluar`, `informe`. |
| `evaluate.py` | Núcleo: recolecta evidencia, evalúa los 11 puntos, calcula el perfil y agrega. |
| `ast_metrics.js` | Análisis del código con ts-morph (complejidad, clases, literales, esquemas, rutas…). |
| `dv8_metrics.py` | Calcula DL y PC con DV8 a partir del grafo de dependencias. |
| `plantilla_manual.py` | Genera la guía y el borrador de la revisión manual. |
| `rubric.json` | **Todos los umbrales, pesos y listas del marco.** Se ajusta aquí, no en el código. |
| `dv8/plantilla-matriz.json` | Plantilla de la matriz de dependencias que consume DV8. |
| `especificaciones/` | Especificaciones técnicas N1–N3, requisitos del dominio y el prompt de generación. |
| `run_experimento.py`, `acceptance_check.py` | Opcionales: generar apps con el CLI de un agente y probarlas contra MongoDB. |
| `docs/` | Metodología, limitaciones y guías. |
| `tests/` | Pruebas del propio evaluador: `python -m unittest discover -s tests -v`. |
| `ejemplo/` | Informe de una corrida real. |

## Documentación

- [Metodología](docs/metodologia.md): qué mide cada punto, cómo se calculan niveles y puntajes, qué es automático y qué manual.
- [Limitaciones](docs/limitaciones.md): lo que el marco **no** garantiza. Léalo antes de citar resultados.
- [Generar las aplicaciones](docs/generar-aplicaciones.md) y [revisión manual](docs/revision-manual.md).

## Adaptarlo

Los umbrales, pesos, tabla de runtimes con soporte, directorios de cada capa y listas de librerías están en
`rubric.json`. La tabla `runtimes_con_soporte` es un supuesto de trabajo: **verifíquela contra las páginas oficiales antes
de congelar un experimento**. Si cambia la rúbrica, ejecute las pruebas del evaluador.
