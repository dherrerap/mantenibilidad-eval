# Limitaciones

Lo que el marco **no** garantiza. Cítelas junto con cualquier resultado.

## Alcance

- **Solo aplicaciones MERN** con carpetas `backend/` y `frontend/`, cada una con su `package.json`. Otras estructuras requieren
  ajustar `ast_metrics.js` y la detección de paquetes.
- **No evalúa si la aplicación funciona.** Sin la compuerta de aceptación (`acceptance_check.py` contra MongoDB) un puntaje
  alto puede corresponder a una app rota. Es una medida de mantenibilidad, no de corrección.
- **Una sola corrida por combinación.** Con una corrida por nivel no hay base estadística para afirmar que un nivel supera a
  otro. Las diferencias de unos pocos puntos están dentro del margen que dejan los criterios pendientes.
- **El resultado es un rango** mientras haya criterios pendientes. Los extremos son cotas, no estimaciones.

## Medición

- **Capas por nombre de directorio.** Es una heurística. Una app que organice sus capas con otros nombres, o que las conecte
  por inyección de dependencias, obtiene "pendiente" y no un resultado automático. Los directorios ambiguos (`domain`, `core`,
  `entities`) también dejan el criterio en revisión.
- **DL y PC sobre una matriz derivada.** DV8 no analiza JavaScript ni TypeScript. La matriz sale del grafo de
  `dependency-cruiser`, con un único tipo de dependencia (`Import`), y los valores pueden diferir de los de un análisis nativo.
  Con proyectos de menos de 100 archivos son sensibles a cada dependencia.
- **Unhealthy Inheritance** se decide con una regla propia (hay o no una clase base del proyecto), no con la detección de DV8:
  `arch-issue` necesita aristas de herencia y, para otros detectores, historial de git, que las aplicaciones evaluadas no tienen.
- **Cobertura con `node --test`.** Las ramas de los archivos que ninguna prueba carga no entran al denominador, así que la
  cobertura de ramas está sobreestimada frente a la de Jest.
- **Observabilidad C1** es un proxy: cuenta bloques `catch` que registran o delegan, no eventos críticos reales.
- **Heurísticas de modelo de datos.** Por ejemplo, un subdocumento embebido en otro esquema puede no detectarse como relación
  explícita. Por eso las sugerencias no cuentan salvo que se acepten.
- **Tecnologías** depende del momento de la consulta: las versiones, deprecaciones y vulnerabilidades de npm cambian con el
  tiempo. La corrida registra la fecha en `entorno.json`. La tabla `runtimes_con_soporte` de `rubric.json` es un supuesto de
  trabajo que debe verificarse a mano.
- **Umbral de duplicación (S1192).** Viene de una práctica externa ampliamente usada, no de un estudio propio de calibración.

## Experimento

- **El modelo generador es una variable.** Si cambia el modelo, el resultado cambia. Registre siempre `--modelo`. Las
  aplicaciones de la corrida de ejemplo se generaron con subagentes cuyo modelo se asumió igual al de la sesión.
- **Las especificaciones difieren en más de un aspecto** entre niveles (estilo arquitectónico, atributos de calidad,
  lineamientos). Una diferencia entre niveles no se puede atribuir a una sola de esas variables.
- **Dominio único.** Los requisitos son los de un e-commerce pequeño (≈ 750–960 líneas de producción por app). No se sabe si
  los resultados se mantienen en aplicaciones más grandes o de otro dominio.

## Seguridad

Ejecutar las pruebas de una aplicación generada por un modelo ejecuta código no confiable: dependencias y scripts de
`npm install` incluidos. Use una máquina virtual o un contenedor desechable.
