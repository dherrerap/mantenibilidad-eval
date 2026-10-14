# Metodología

Esta página describe qué mide el marco y cómo se obtiene cada número. Los valores exactos están en `rubric.json`; si alguien
los cambia, esta página puede quedar desactualizada y manda el archivo.

## Estructura

Se evalúan **11 puntos de decisión**. Cada punto tiene criterios (C1, C2, …) que se cumplen o no, y de ahí sale un nivel.
Cada punto contribuye a una o más subcaracterísticas, y estas se ponderan en un puntaje global de 0 a 100.

## Niveles

Para un punto con *n* criterios:

- **Cumple**: se cumplen todos.
- **Parcial**: se cumple al menos la mitad (`parcial_min_fraccion = 0.5`).
- **No cumple**: se cumplen menos de la mitad.
- Un criterio **obligatorio** que falla fuerza "No cumple": `contratos.C1` (contrato legible por máquina) y `pruebas.C2`
  (existen pruebas y pasan).

Capas y complejidad ciclomática usan además umbrales porcentuales (ver abajo).

## Puntajes

- Cada nivel vale: Cumple = 1, Parcial = 0,5, No cumple = 0.
- El puntaje de una subcaracterística es el promedio de los puntos que la alimentan, por 100.
- El puntaje global es la suma ponderada: Testabilidad 30 %, Analizabilidad 24 %, Modularidad 24 %, Modificabilidad 22 %.
- **Rangos.** Un criterio pendiente (`ok = null`) se evalúa dos veces, como cumplido y como no cumplido. El punto, la
  subcaracterística y el global se expresan entonces como `mínimo–máximo`. Cuando todo está resuelto, el rango se colapsa a un
  número y `completo = true`.

## Los 11 puntos

La columna *Tipo* indica cómo se decide: **auto** (sin intervención), **mixto** (el programa calcula y una persona confirma
o completa) o **manual**.

| Punto | Subcaracterísticas | Criterios | Tipo |
|---|---|---|---|
| **Capas** | Modularidad | C1 al menos 2 capas identificables · C2 violaciones ≤ 5 % de las dependencias entre capas (Cumple con 0 %, Parcial hasta 5 %). Solo se permiten presentación→negocio y negocio→datos. | auto, con revisión si la evidencia es ambigua |
| **Complejidad ciclomática** | Modularidad, Modificabilidad | X = 1 − (funciones con CC > 20)/(total). Cumple X ≥ 0,98 · Parcial X ≥ 0,95. | auto |
| **Cohesión** | Modularidad, Modificabilidad | C1 ≤ 5 % de funciones con fan-out > 5 · C2 DL (DV8) ≥ 60 % · C3 lista de verificación sin hallazgos (módulo "dios", mezcla de responsabilidades, fragmentación). | mixto |
| **Jerarquías** | Modularidad | C1 profundidad de herencia ≤ 7 · C2 ≤ 10 hijos directos · C3 0 patrones Unhealthy Inheritance. | auto |
| **Tecnologías** | Analizabilidad, Modificabilidad | C1 sin paquetes deprecados · C2 runtime y framework con soporte (tabla en `rubric.json`) · C3 ≤ 20 % de dependencias directas con versión mayor atrasada · C4 0 vulnerabilidades altas o críticas (`npm audit`). Consulta el registro de npm. | auto con red |
| **Acoplamiento** | Modularidad | C1 0 ciclos · C2 X (MMo-1-G) ≥ 0,90 · C3 Propagation Cost (DV8) ≤ 20 % · C4 ≤ 10 % de dependencias sin uso (`depcheck`). | auto |
| **Modelo de datos** | Modularidad, Analizabilidad | C1 entidades y relaciones explícitas · C2 referencia o embebido coherente con el acceso · C3 validación de esquema · C4 índices en campos de consulta y relación · C5 sin redundancia injustificada ni tipos inconsistentes. | manual (con sugerencias) |
| **Contratos** | Modularidad, Testabilidad | C1 contrato legible por máquina (OpenAPI…) · C2 0 errores de Spectral · C3 cobertura del contrato ≥ 90 % de las rutas · C4 validación de entradas coherente con el contrato. | mixto |
| **Observabilidad** | Analizabilidad | C1 ≥ 80 % de eventos críticos registrados (aproximado con bloques `catch` que hacen log o delegan a un manejador que registra) · C2 logger estructurado y sin `console.*` · C3 manejo centralizado de errores · C4 health check, métricas o trazas. | mixto |
| **Pruebas** | Testabilidad | C1 0 violaciones CWE-478/484/1075 · C2 pruebas existentes y aprobadas · C3 cobertura de líneas ≥ 70 % · C4 cobertura de ramas ≥ 50 %. | auto (requiere ejecutar las pruebas) |
| **Configuración** | Modificabilidad | C1 0 literales de red (URL, IP, puerto) · C2 sin literales duplicados según S1192 · C3 configuración externa (`.env.example` o módulo de configuración). | auto |

### Notas por punto

- **Capas.** La capa de cada archivo se deduce del nombre de sus directorios (`controllers`, `services`, `models`…), con la
  tabla de `rubric.json`. Puede sustituirse por un `.layers.json` dentro de la app. Dos situaciones no se resuelven solas y
  dejan C2 pendiente: **(a)** cero dependencias entre capas (típico con inyección de dependencias: nada importa a nada, así
  que no hay evidencia estructural) y **(b)** una violación que depende de un directorio ambiguo como `domain` o `core`, que
  según la arquitectura puede ser negocio o el núcleo de la aplicación.
- **Configuración C2.** Usa la regla S1192 de SonarQube (`no-duplicate-string` en `eslint-plugin-sonarjs`): umbral de 3
  repeticiones, longitud mínima de 10, sin literales formados solo por caracteres de palabra y sin `application/json`. Valores
  verificados contra el código del plugin. Es una regla **absoluta**: no depende de las otras aplicaciones evaluadas.
- **DL y PC (DV8).** Se calculan sobre una matriz de dependencias construida a partir del grafo de módulos, con el tipo de
  dependencia `Import`. DV8 no analiza JavaScript ni TypeScript por sí mismo. Se usan los valores **sin archivos aislados**,
  porque DV8 reporta 100 % de DL cuando hay un archivo aislado (por ejemplo `vite.config.js`) y eso distorsiona el resultado.
  Ambos valores quedan registrados.
- **Unhealthy Inheritance.** Necesita una clase base definida en el proyecto. Si ninguna clase extiende a otra del proyecto
  (todas heredan de `Error`, por ejemplo) el conteo es 0. Si existe una jerarquía propia, queda pendiente y se revisa a mano
  con los dos criterios de DV8: un padre que depende de su hijo, o un cliente que depende de ambos.
- **Cobertura.** Con Jest se lee `coverage-summary.json` contando también los archivos que ninguna prueba carga. Con el runner
  nativo de Node (`node --test`) se lee el reporte lcov y los archivos sin cargar se suman como 0 % de líneas; sus ramas no
  entran al denominador.

## Heurísticas

Algunos criterios traen una sugerencia automática (modelo de datos C1/C3/C4, contratos C4, cohesión C3). **No cuentan** como
resultado salvo que se pase `--aceptar-heuristicas`; por defecto solo orientan a quien hace la revisión.

## Trazabilidad

Cada ejecución deja en `resultados/<app>/`: `perfil.md` y `perfil.json` (resultado), `ficha.json` y `ficha.csv` (los 11 puntos
con sus criterios y evidencia), `trazabilidad.csv`, `metrics.json` (evidencia cruda), `layers_detectadas.json` (capa de cada
archivo y qué directorio la decidió) y la carpeta `dv8/` con la matriz y las métricas. `resultados/entorno.json` registra
las versiones usadas.
