# Revisión manual

Algunos criterios no se pueden decidir con un programa. Quedan **pendientes** y el puntaje es un rango hasta que una persona
los resuelva. Esta página explica cómo hacerlo y cómo se combinan las fuentes.

## Qué se revisa

| Punto | Criterio | Qué se decide |
|---|---|---|
| Capas | C2 | Solo si no hay dependencias entre capas, o si una violación depende de un directorio ambiguo. `true`: la separación es real (o la dependencia dudosa es legítima en esa arquitectura). `false`: hay acoplamiento indebido. |
| Cohesión | C3 | No hay módulo "dios", mezcla de responsabilidades distintas en un módulo ni fragmentación excesiva. |
| Modelo de datos | C1 a C5 | Entidades y relaciones explícitas · referencia/embebido coherente con el acceso · validación de esquema · índices · sin redundancia. |
| Contratos | C4 | La validación de entradas es coherente con el contrato. |
| Jerarquías | C3 | Solo si el proyecto define una clase base propia (Unhealthy Inheritance). |

## Procedimiento

1. Ejecute `python eval.py evaluar`. Por cada app se crean, en `resultados/<app>/`:
   - `revision_manual.md`: enunciado, evidencia (tablas, funciones con fan-out alto, código de los modelos) y una sugerencia
     por criterio.
   - `revision_manual.borrador.json`: la misma estructura con `ok: null`.
2. Revise la evidencia. Las sugerencias **orientan, no deciden**; pueden estar equivocadas (por ejemplo, no detectar un
   subdocumento embebido).
3. Copie el borrador a `revision_manual.json` en la misma carpeta y reemplace `ok` por `true` o `false`. El campo `nota`
   queda registrado como valor del criterio: úselo para justificar.
4. Ejecute otra vez `python eval.py evaluar`. El rango se estrecha o se cierra, y el informe lista lo que aún queda.

Ejemplo de `revision_manual.json`:

```json
{
  "capas":        { "C2": { "ok": true,  "nota": "Los servicios reciben repositorios por inyección; ninguna capa importa a otra." } },
  "modelo_datos": { "C1": { "ok": true,  "nota": "lineSchema embebido en orderSchema." },
                    "C2": { "ok": true,  "nota": "Las líneas viajan con el pedido." } }
}
```

Solo hace falta incluir los criterios que decida; los demás pueden omitirse o quedar en `null`.

## De dónde se leen los valores (prioridad)

La revisión manual: `--manual` indicado a `evaluate.py` > `<app>/manual.json` > `resultados/<app>/revision_manual.json`.

Valores de DV8 (`dv8.DL`, `dv8.PC`, `dv8.unhealthy_inheritance`): el valor explícito en el manual > `resultados/<app>/dv8/dv8_manual.json`
(revisión humana, que ninguna ejecución sobrescribe) > `resultados/<app>/dv8/dv8_metrics.json` (calculado). Use
`dv8_manual.json` para dejar constancia de una revisión, por ejemplo la de Unhealthy Inheritance:

```json
{ "unhealthy_inheritance": 0,
  "_revision": { "conclusion": "AppError no referencia a sus subclases y ningún archivo importa al padre y a un hijo." } }
```

## Clasificación de capas explícita

Si la heurística por directorio no refleja la arquitectura, cree `<app>/.layers.json` con globs por capa y vuelva a evaluar:

```json
{ "presentacion": ["backend/src/http/**"], "negocio": ["backend/src/services/**", "backend/src/domain/**"],
  "datos": ["backend/src/repositories/**"], "compartida": ["backend/src/errors.js", "backend/src/config.js"] }
```

`resultados/<app>/layers_detectadas.json` muestra la capa que recibió cada archivo y el directorio que la decidió.
