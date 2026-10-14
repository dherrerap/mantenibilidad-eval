# Informe de mantenibilidad

Generado: 2026-10-14 00:05 · 3 aplicación(es)

## Resultado global (0–100)

| Aplicación | Nivel | Global | Testabilidad | Analizabilidad | Modularidad | Modificabilidad | Completo |
|---|---|---|---|---|---|---|---|
| claude-n1-ecommerce-r1 | N1 | **40.2–56.1** | 25.0 | 33.3–66.7 | 57.1–78.6 | 50.0–62.5 | no |
| claude-n2-ecommerce-r1 | N2 | **36.8–56.1** | 25.0 | 33.3–66.7 | 42.9–78.6 | 50.0–62.5 | no |
| claude-n3-ecommerce-r1 | N3 | **36.8–56.1** | 25.0 | 33.3–66.7 | 42.9–78.6 | 50.0–62.5 | no |

Un rango (a–b) indica criterios pendientes: el valor real queda entre ambos extremos hasta completar la revisión manual.

## Puntos de decisión

✔ Cumple · ◐ Parcial · ✘ No cumple · a…b rango por criterios pendientes · ? sin evaluar

| Punto | claude-n1-ecommerce-r1 | claude-n2-ecommerce-r1 | claude-n3-ecommerce-r1 |
|---|---|---|---|
| Separación de responsabilidades entre capas | ✔ | ✘…✔ | ✘…✔ |
| Complejidad ciclomática | ✔ | ✔ | ✔ |
| Cohesión de los módulos de responsabilidad compartida | ✘…◐ | ✘…◐ | ✘…◐ |
| Profundidad y amplitud de las jerarquías de herencia o composición | ✔ | ✔ | ✔ |
| Selección de tecnologías/frameworks y riesgo de obsolescencia | ◐ | ◐ | ◐ |
| Acoplamiento externo y volumen de dependencias declaradas | ✔ | ✔ | ✔ |
| Diseño del modelo de datos | ✘…✔ | ✘…✔ | ✘…✔ |
| Definición de contratos de comunicación entre componentes | ✘ | ✘ | ✘ |
| Presencia y consistencia de mecanismos de observabilidad | ◐ | ◐ | ◐ |
| Coberturas y diseño de pruebas | ◐ | ◐ | ◐ |
| Separación de configuración y código | ◐ | ◐ | ◐ |

## Pendientes de revisión manual

- **claude-n1-ecommerce-r1** — cohesion: C3; modelo_datos: C1, C2, C3, C4, C5; contratos: C4 → `claude-n1-ecommerce-r1/revision_manual.md`
- **claude-n2-ecommerce-r1** — capas: C2; cohesion: C3; modelo_datos: C1, C2, C3, C4, C5; contratos: C4 → `claude-n2-ecommerce-r1/revision_manual.md`
- **claude-n3-ecommerce-r1** — capas: C2; cohesion: C3; modelo_datos: C1, C2, C3, C4, C5; contratos: C4 → `claude-n3-ecommerce-r1/revision_manual.md`

## Hallazgos por aplicación

### claude-n1-ecommerce-r1
- **Cohesión de los módulos de responsabilidad compartida** (✘…◐): 5 de 121 funciones con fan-out > 5; 0 módulo(s) candidatos a 'dios'.
- **Selección de tecnologías/frameworks y riesgo de obsolescencia** (◐): 10 dependencias directas: 0 deprecadas, 8 con mayor atrasada, 1 vulnerabilidades altas/críticas.
- **Diseño del modelo de datos** (✘…✔): 4 esquemas Mongoose detectados.
- **Definición de contratos de comunicación entre componentes** (✘): Sin contrato legible por máquina; 7 rutas implementadas.
- **Presencia y consistencia de mecanismos de observabilidad** (◐): 4 bloques catch (0 con log, 4 delegan, 0 silenciosos); 4 console.*; 1 middleware(s) de errores.
- **Coberturas y diseño de pruebas** (◐): 2 casos de prueba; cobertura líneas 5%, ramas 100%.
- **Separación de configuración y código** (◐): 7 literales de red; 0 literal(es) duplicado(s) según S1192 (35.8 repeticiones/KLOC, informativo).

### claude-n2-ecommerce-r1
- **Separación de responsabilidades entre capas** (✘…✔): Capas detectadas: datos, negocio, presentacion; 1 de 13 dependencias violan la regla, 1 por una clasificación dudosa (directorio ambiguo): de No cumple a Cumple según la revisión manual (capas.C2) o un .layers.json.
- **Cohesión de los módulos de responsabilidad compartida** (✘…◐): 5 de 145 funciones con fan-out > 5; 0 módulo(s) candidatos a 'dios'.
- **Selección de tecnologías/frameworks y riesgo de obsolescencia** (◐): 10 dependencias directas: 0 deprecadas, 8 con mayor atrasada, 1 vulnerabilidades altas/críticas.
- **Diseño del modelo de datos** (✘…✔): 4 esquemas Mongoose detectados.
- **Definición de contratos de comunicación entre componentes** (✘): Sin contrato legible por máquina; 7 rutas implementadas.
- **Presencia y consistencia de mecanismos de observabilidad** (◐): 4 bloques catch (0 con log, 4 delegan, 0 silenciosos); 3 console.*; 1 middleware(s) de errores.
- **Coberturas y diseño de pruebas** (◐): 6 casos de prueba; cobertura líneas 11%, ramas 92%.
- **Separación de configuración y código** (◐): 7 literales de red; 0 literal(es) duplicado(s) según S1192 (33.6 repeticiones/KLOC, informativo).

### claude-n3-ecommerce-r1
- **Separación de responsabilidades entre capas** (✘…✔): Capas detectadas: datos, negocio, presentacion; 0 dependencias entre capas (posible inyección de dependencias): no hay evidencia estructural; requiere revisión manual (capas.C2).
- **Cohesión de los módulos de responsabilidad compartida** (✘…◐): 6 de 183 funciones con fan-out > 5; 0 módulo(s) candidatos a 'dios'.
- **Selección de tecnologías/frameworks y riesgo de obsolescencia** (◐): 10 dependencias directas: 0 deprecadas, 8 con mayor atrasada, 1 vulnerabilidades altas/críticas.
- **Diseño del modelo de datos** (✘…✔): 4 esquemas Mongoose detectados.
- **Definición de contratos de comunicación entre componentes** (✘): Sin contrato legible por máquina; 7 rutas implementadas.
- **Presencia y consistencia de mecanismos de observabilidad** (◐): 4 bloques catch (0 con log, 3 delegan, 1 silenciosos); 4 console.*; 1 middleware(s) de errores.
- **Coberturas y diseño de pruebas** (◐): 23 casos de prueba; cobertura líneas 31%, ramas 94%.
- **Separación de configuración y código** (◐): 7 literales de red; 0 literal(es) duplicado(s) según S1192 (26.0 repeticiones/KLOC, informativo).

## Advertencias metodológicas

- Cada nivel tiene una sola corrida: las diferencias entre niveles no son estadísticamente concluyentes.
- Las aplicaciones no se ejecutan contra MongoDB (sin compuerta de aceptación): no se sabe si funcionan.
- La clasificación de capas es heurística por nombre de directorio; revise `layers_detectadas.json`.
- Cobertura de pruebas: con `node --test` se suman como 0% los archivos que ninguna prueba carga, pero sus ramas no entran al denominador (ramas sobreestimadas).
- DL y PC de DV8 se calculan sobre una matriz derivada de dependency-cruiser (DV8 no analiza JS/TS) y sin archivos aislados.

## Entorno

Python 3.12.10 · Node v22.17.1 · npm 10.5.0 · DV8: C:\Program Files\DV8\bin\dv8-console.exe
Sistema: Windows-11-10.0.26300-SP0 · evaluado el 2026-10-13T23:58:57 · tabla de runtimes con soporte fechada 2026-10-14
