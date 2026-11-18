# Verificación de las aplicaciones ecommerce

Fecha: 2026-11-16 (America/Costa_Rica).

Se generaron tres aplicaciones de la fase inicial con tres subagentes sin historial heredado. Cada agente recibió únicamente la ruta de su carpeta y las instrucciones para leer `PROMPT.md`, `requirements-ecommerce.md` y su propio `technical-n*.md`. Se prohibió consultar otros directorios, agentes, servicios de búsqueda o conectores. El aislamiento fue por contexto e instrucciones, aceptado expresamente por el usuario; no hubo un bloqueo de acceso al sistema de archivos por subagente.

La sesión principal no abrió ni evaluó las entregas hasta que los tres agentes finalizaron. Las comprobaciones posteriores no modificaron el código generado. No se implementó la fase R2.

| Aplicación | Instrucciones | Pruebas reportadas por el subagente | API con PostgreSQL real | Integración propia con PostgreSQL real | Build frontend |
| --- | --- | --- | --- | --- | --- |
| N1 | [README](../apps/codex-ecommerce-n1/README.md) | 5 aprobadas | 20/20 | 1/1 aprobada | Aprobado |
| N2 | [README](../apps/codex-ecommerce-n2/README.md) | 7 aprobadas | 20/20 | 1/1 aprobada | Aprobado |
| N3 | [README](../apps/codex-ecommerce-n3/README.md) | 22 aprobadas | 20/20 | Sin suite separada; API real comprobada desde la sesión principal | Aprobado |

## Comprobaciones posteriores de la sesión principal

Se inició una instancia temporal independiente de PostgreSQL 18.6 en loopback y se creó una base distinta para cada aplicación. No se usaron las bases existentes del usuario. Se ejecutó `npm start` en cada backend con `PORT`, `DATABASE_URL` y `JWT_SECRET` configurados para la prueba.

Al terminar se detuvieron los backends de prueba y la instancia temporal de PostgreSQL.

Las 20 comprobaciones por aplicación cubren: los productos iniciales; registro y duplicados; credenciales incorrectas; login; protección de rutas; los tres ejemplos de descuento; la cotización combinada de 47; cantidades negativas; reversión de todos los productos ante stock insuficiente; persistencia del pedido y descuento de stock; privacidad de pedidos; rechazo de saltos y retrocesos de estado; avances válidos; agotamiento de Mug y compras simultáneas sin sobreventa.

Los resultados de las 60 comprobaciones están en [generated-ecommerce-checks.json](generated-ecommerce-checks.json). El script independiente está en [generated-ecommerce-verify.mjs](generated-ecommerce-verify.mjs); se ejecuta con `node docs/generated-ecommerce-verify.mjs http://127.0.0.1:PUERTO ruta-salida.json` contra un backend conectado a una base recién inicializada. Modifica sus datos de prueba, por lo que debe usarse exclusivamente con una base desechable.

También se ejecutó `npm run test:integration` de N1 y N2 con `TEST_DATABASE_URL` apuntando a bases temporales exclusivas: ambas suites pasaron sin omisiones. N3 fue verificada contra PostgreSQL real mediante las mismas 20 comprobaciones externas, incluyendo migración inicial, semilla y concurrencia de stock.

Los tres `npm run build` de frontend finalizaron correctamente y generaron sus carpetas `frontend/dist`. Fue necesario ejecutarlos fuera del sandbox porque el resolvedor de esbuild recibe `Access denied` al consultar directorios ancestros dentro del sandbox. No se cambiaron dependencias ni código para superar esa limitación.

Se verificó la presencia de los archivos de entrega, la sintaxis de los tres documentos OpenAPI 3, sus siete operaciones y la presencia de los diagramas Mermaid ER. Esto no equivale a una evaluación completa de conformidad de contratos ni de mantenibilidad.

## Alcance y límites

Los informes internos de los subagentes describen las limitaciones que tenían durante la generación; este informe registra las comprobaciones adicionales realizadas posteriormente por la sesión principal. No se ejecutaron pruebas visuales en navegador ni Docker Compose. Cada aplicación utiliza por defecto los mismos puertos locales; para ejecutarlas simultáneamente hay que asignar puertos y bases distintos siguiendo sus README.
