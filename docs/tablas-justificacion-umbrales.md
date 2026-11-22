# Justificación y trazabilidad de métricas y umbrales

## Alcance de cada estándar respecto de las métricas y los umbrales del marco

| Estándar             | Aporta                                                                                                                                                          | No aporta                                                                                                          |
| -------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| ISO/IEC 25010 (2023) | La definición de mantenibilidad y de sus cinco subcaracterísticas; la adscripción de cada punto de decisión a la subcaracterística afectada                     | Ninguna medida ni ningún umbral: es un modelo de calidad                                                           |
| ISO/IEC 25023 (2016) | Las funciones de medición, de la forma X = A/B o X = 1 − A/B; el nivel de recomendación de cada medida; los requisitos de conformidad de la cláusula 2          | Ningún valor de corte                                                                                              |
| ISO/IEC 5055 (2021)  | Umbrales numéricos por defecto para varias de las 29 debilidades de mantenibilidad; el conteo de ocurrencias como forma de cálculo; la normalización por tamaño | Nada sobre esquemas relacionales, obsolescencia de dependencias, contratos de comunicación ni cobertura de pruebas |
| IEEE Std 1028 (2008) | El proceso de revisión: roles, criterios de entrada y de salida, escala de ordenamiento de anomalías y tasas de inspección                                      | Ninguna métrica de producto ni umbral de código                                                                    |

## Umbrales con respaldo normativo exacto

| Umbral del instrumento               | Valor     | Criterio que decide              | Fuente               | Debilidad o cláusula                                 |
| ------------------------------------ | --------- | -------------------------------- | -------------------- | ---------------------------------------------------- |
| Complejidad ciclomática por función  | 20        | Complejidad ciclomática, C1 y C2 | ISO/IEC 5055 (2021)  | CWE-1121, complejidad ciclomática de McCabe excesiva |
| Fan-out por función                  | 5         | Cohesión, C1                     | ISO/IEC 5055 (2021)  | CWE-1048, acoplamiento o fan-out excesivo            |
| Líneas de código por archivo         | 1000      | Cohesión, C4                     | ISO/IEC 5055 (2021)  | CWE-1080, archivo con número excesivo de líneas      |
| Componente de tamaño del módulo dios | 1000      | Cohesión, C3                     | ISO/IEC 5055 (2021)  | CWE-1080                                             |
| Profundidad de herencia              | 7         | Jerarquías, C1                   | ISO/IEC 5055 (2021)  | CWE-1074, clase con herencia excesivamente profunda  |
| Clases hijas directas                | 10        | Jerarquías, C2                   | ISO/IEC 5055 (2021)  | CWE-1086, clase con número excesivo de clases hijas  |
| Archivos estructuralmente muertos    | 0         | Acoplamiento, C5                 | ISO/IEC 5055 (2021)  | CWE-561, código muerto                               |
| Parámetros por función               | 7         | Indicador ASCMM (informativo)    | ISO/IEC 5055 (2021)  | CWE-1064, firma con número excesivo de parámetros    |
| Escala de severidad                  | 4 niveles | Severidad de todos los puntos    | IEEE Std 1028 (2008) | 6.8.3                                                |

## Umbrales con respaldo normativo parcial

La norma sostiene la medida, pero no el valor exacto: o bien cuenta ocurrencias sin publicar un valor por defecto (conteo de cero), o
bien publica un valor que aquí se aplica con otra base o granularidad (alternativo), o bien solo aporta la función de medición, sin
valor de corte (solo función).

| Umbral                                   | Valor         | Criterio que decide                 | Tipo de respaldo | Fuente y desviación                                                                                     |
| ---------------------------------------- | ------------- | ----------------------------------- | ---------------- | ------------------------------------------------------------------------------------------------------- |
| Violaciones de capas para _Cumple_       | 0 %           | Capas, C2                           | Conteo de cero   | ISO/IEC 5055, CWE-1054: se puntúa contando ocurrencias, sin valor por defecto                          |
| Ocurrencias de debilidades informativas  | 0             | Indicadores ASCMM (informativo)     | Conteo de cero   | ISO/IEC 5055, CWE-480, 570, 571, 783 y 1095                                                             |
| Dependencias salientes por módulo        | 10            | Acoplamiento, C2 (numerador)        | Alternativo      | ISO/IEC 5055, CWE-1048: 5 referencias por función; aquí, 10 dependencias distintas por módulo           |
| Líneas duplicadas                        | 10 %          | Complejidad ciclomática, C3         | Alternativo      | ISO/IEC 5055, CWE-1041: 10 % de las instrucciones de cada instancia de clon; aquí, líneas de toda la app |
| Código comentado por función             | 2 %           | Indicador ASCMM (informativo)       | Alternativo      | ISO/IEC 5055, CWE-1085: instrucciones comentadas; aquí, líneas comentadas de la función                 |
| Props por componente                     | 7             | Indicador suplementario (informativo) | Alternativo    | ISO/IEC 5055, CWE-1064: parámetros de una función, aplicado a las props de un componente React          |
| X de complejidad ciclomática             | 0,95 y 0,98   | Complejidad ciclomática, C1 y C2    | Solo función     | ISO/IEC 25023, MMo-2-S: X = 1 − A/B, sin valor de corte                                                 |
| X de acoplamiento entre componentes      | 0,90          | Acoplamiento, C2                    | Solo función     | ISO/IEC 25023, MMo-1-G: X = A/B, sin valor de corte                                                     |
| Completitud del registro del sistema     | 80 %          | Observabilidad, C1                  | Solo función     | ISO/IEC 25023, MAn-1-G: X = A/B, sin valor de corte                                                     |

## Umbrales sin respaldo en los estándares del estudio

| Umbral                                 | Valor               | Criterio o efecto                       | Decide un veredicto            |
| -------------------------------------- | ------------------- | --------------------------------------- | ------------------------------ |
| Pesos de las subcaracterísticas        | 30 / 24 / 24 / 22 % | Puntaje global                          | Sí                             |
| Agregación de los puntos dentro de cada subcaracterística | Promedio simple (`point_weights` vacío) | Peso efectivo de cada punto en el puntaje global (de 3,4 % a 18,4 %) | Sí |
| Fracción mínima para _Parcial_         | 0,5                 | Nivel de todos los puntos               | Sí                             |
| Puntaje por nivel                      | 1 / 0,5 / 0         | Puntaje de todas las subcaracterísticas | Sí                             |
| Violaciones de capas para _Parcial_    | 5 %                 | Capas, C2                               | Sí                             |
| Capas identificables mínimas           | 2                   | Capas, C1                               | Sí                             |
| Funciones con fan-out excesivo         | 5 %                 | Cohesión, C1                            | Sí                             |
| _Decoupling Level_ mínimo              | 60 %                | Cohesión, C2                            | Sí                             |
| Fan-in del módulo dios                 | 8                   | Cohesión, C3                            | Solo con heurísticas aceptadas |
| Dependencias con mayor desactualizado  | 20 %                | Tecnologías, C3                         | Sí                             |
| Vulnerabilidades altas o críticas      | 0                   | Tecnologías, C4                         | Sí                             |
| _Propagation Cost_ máximo              | 20 %                | Acoplamiento, C3                        | Sí                             |
| Dependencias no utilizadas             | 10 %                | Acoplamiento, C4                        | Sí                             |
| Columnas con restricción declarada     | 50 %                | Modelo de datos, C3                     | Sí                             |
| Filtros de consulta sin índice         | 0 %                 | Modelo de datos, C4                     | Sí                             |
| Cobertura del contrato sobre rutas     | 90 %                | Contratos, C3                           | Sí                             |
| Cobertura de línea                     | 70 %                | Pruebas, C3                             | Sí                             |
| Cobertura de rama                      | 50 %                | Pruebas, C4                             | Sí                             |
| Cortes del semáforo                    | 70 y 40             | Estado de la tabla de riesgo            | Sí                             |
| Puntos de entrada adicionales de Knip  | 7 nombres y 2 patrones | Acoplamiento, C5, detección          | Sí, indirectamente             |
| Inclusión de _devDependencies_         | falso               | Acoplamiento, C4, denominador           | Sí, indirectamente             |
| Literal de red con respaldo de entorno | falso               | Configuración, C1, detección            | Sí, indirectamente             |
| Versiones de runtime soportadas        | tabla               | Tecnologías, C2                         | Sí, con fuente externa         |
| Complejidad cognitiva por función      | 15                  | Informativo                             | No                             |
| Líneas y tokens mínimos de clon        | 5 y 50              | Cyclomática, C3, detección              | Sí, indirectamente             |
| Repeticiones de literal duplicado      | 3 y exenciones      | Configuración, C2, detección (S1192; el largo mínimo de 10 lo fija la regla) | Sí, indirectamente |
| Razón de líneas de prueba              | 0,3                 | Informativo                             | No                             |
| Funciones con JSDoc                    | 50 %                | Informativo                             | No                             |
| Líneas por componente                  | 150                 | Informativo                             | No                             |
| Campos del contrato presentes          | 80 %                | Informativo                             | No                             |
| Focos por indicador                    | 5                   | Presentación                            | No                             |

## Referencias

IEEE. (2008). _IEEE Std 1028-2008: IEEE standard for software reviews and audits_. Institute of Electrical and Electronics Engineers.

ISO/IEC. (2016). _ISO/IEC 25023:2016. Systems and software engineering — Systems and software Quality Requirements and Evaluation (SQuaRE) — Measurement of system and software product quality_. International Organization for Standardization.

ISO/IEC. (2021). _ISO/IEC 5055:2021. Information technology — Software measurement — Software quality measurement — Automated source code quality measures_. International Organization for Standardization.

ISO/IEC. (2023). _ISO/IEC 25010:2023. Systems and software engineering — Systems and software Quality Requirements and Evaluation (SQuaRE) — Product quality model_. International Organization for Standardization.
