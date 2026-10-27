# Methodology

This page describes what the framework measures and how each number is obtained. The exact values are in `rubric.json`; if someone
changes them, this page may become outdated and the file takes precedence.

## Protocol steps (as implemented)

2. **Collect and classify the generated artifacts** according to Table 27 into three levels: **core**, without which the decision point
   is not evaluable; **complementary**, whose absence does not invalidate the evaluation but is recorded as a finding and lowers the
   point's confidence; and **optional**, which enrich the analysis when available.
9. **Apply the weighting scheme** to the classified findings to obtain the maintainability profile.
10. **Generate the maintainability risk dashboard** from the profile, applying the rules of Table 29, and identify the decision points
    that are not evaluable for lack of evidence.

(Steps 3-8 are the evidence collection, per-point evaluation and traceability described below.)

## Input artifacts (Table 27)

| Artifact | Level | Decision points it feeds | Evidence |
|---|---|---|---|
| Source code | Core | Layers, complexity, cohesion, hierarchies | Structural |
| Data model schema / migrations | Core | Data model design | Structural |
| Manifests and lockfiles | Core | Technology selection, external coupling | Structural |
| Test suite, scripts and coverage report | Complementary* | Test coverage and design | Structural |
| Contract specification (OpenAPI, JSON Schema, DTOs) | Complementary | Communication contracts | Structural |
| Configuration and deployment (.env.example, Dockerfile, CI) | Complementary | Separation of configuration and code | Structural |
| Logging and metrics configuration | Complementary | Observability | Structural |
| README, wiki, ADRs | Complementary | Analyzability (declarative vs. structural contrast) | Declarative |
| Architecture diagrams | Complementary | Triangulation | Declarative or derived |
| Agent prompt and session record | Complementary | Step 1 (specificity level) | Contextual |
| Domain glossary or ontology | Optional | Analyzability | Declarative |

\* The absence of a test suite is not treated as missing data but as a **high-severity finding**.

How the framework applies it (`inventory_artifacts` in `evaluate.py`; the table itself is in `rubric.json` under `artifacts`, so the
mapping is editable):

- **Core artifact missing** → the points it feeds are **not evaluable**: no level, no score, and they are excluded from the subcharacteristic
  averages. They are shown as ▨ "not evaluable", never as "Meets".
- **Complementary artifact missing** → a finding (Medium; High for the test suite) in `profile.json` / `profile.md`, and the confidence of
  each affected point drops: `high` (nothing missing), `medium` (one missing), `low` (two or more). A High finding also raises the point's
  severity to High.
- **Optional artifacts** never produce findings.
- Detection is by file patterns and parsed evidence (e.g. the test suite is "present" if test cases are found; the logging configuration
  if a logger or metrics library is declared). The result is saved in `artifacts.json` and in the "Input artifacts" section of `profile.md`.

## Risk dashboard (Table 29)

| Level | Content | Rule |
|---|---|---|
| Semaphore per subcharacteristic | 4 indicators | Green / yellow / red according to the profile's weighted score. The cut-offs are configurable like the weights (`risk_dashboard.semaphore` in `rubric.json`: green ≥ 70, yellow ≥ 40 by default). With a score range, the worst case (minimum) decides. |
| Heat map points × subcharacteristics | 11 × 4, only cells related in Table 24 | Meets = green, Partial = yellow, Fails = red (Table 26). Unrelated cells are gray. |
| Escalation | All cells | A high-severity finding forces red even if the average is acceptable. Escalated cells are marked ↑. |
| Not evaluable | Points without evidence | Gray with a hatch pattern and the label "not evaluable", distinct from "Meets". |
| Module hotspots (optional) | Automatable indicators only | The N worst files by complexity, layer violations and cyclic dependencies (`risk_dashboard.hotspots_top_n`, default 5). |

Outputs per run: `risk_dashboard.html` (visual, with the hatch pattern), `risk_dashboard.md` and `risk_dashboard.json`; the same data is in
`profile.json` under `dashboard`. `report.md` shows the semaphore of every application side by side, the not-evaluable points and the hotspots.
Undecided cells (pending criteria) are shown as ⚪ and are not counted as green or red.

## Structure

**11 decision points** are evaluated. Each point has criteria (C1, C2, …) that are either met or not, and a level comes out of that.
Each point contributes to one or more subcharacteristics, and these are weighted into an overall score from 0 to 100.

## Levels

For a point with *n* criteria:

- **Meets**: all are met.
- **Partial**: at least half are met (`partial_min_fraction = 0.5`).
- **Fails**: fewer than half are met.
- A failing **mandatory** criterion forces "Fails": `contracts.C1` (machine-readable contract) and `tests.C2`
  (tests exist and pass).

Layers and cyclomatic complexity additionally use percentage thresholds (see below).

## Scores

- Each level is worth: Meets = 1, Partial = 0.5, Fails = 0.
- A subcharacteristic's score is the average of the points that feed it, times 100.
- The overall score is the weighted sum: Testability 30%, Analyzability 24%, Modularity 24%, Modifiability 22%.
- **Ranges.** A pending criterion (`ok = null`) is evaluated twice, as met and as not met. The point, the
  subcharacteristic and the overall score are then expressed as `minimum–maximum`. When everything is resolved, the range collapses to a
  single number and `complete = true`.

## The 11 points

The *Type* column indicates how it is decided: **auto** (no intervention), **mixed** (the program computes and a person confirms
or completes) or **manual**.

| Point | Subcharacteristics | Criteria | Type |
|---|---|---|---|
| **Layers** | Modularity | C1 at least 2 identifiable layers · C2 violations ≤ 5% of inter-layer dependencies (Meets at 0%, Partial up to 5%). Only presentation→business and business→data are allowed. | auto, with review if the evidence is ambiguous |
| **Cyclomatic complexity** | Modularity, Modifiability | X = 1 − (functions with CC > 20)/(total). Meets X ≥ 0.98 · Partial X ≥ 0.95. | auto |
| **Cohesion** | Modularity, Modifiability | C1 ≤ 5% of functions with fan-out > 5 · C2 DL (DV8) ≥ 60% · C3 checklist with no findings ("god" module, mixed responsibilities, fragmentation). | mixed |
| **Hierarchies** | Modularity | C1 inheritance depth ≤ 7 · C2 ≤ 10 direct children · C3 0 Unhealthy Inheritance patterns. | auto |
| **Technologies** | Analyzability, Modifiability | C1 no deprecated packages · C2 runtime and framework supported (table in `rubric.json`) · C3 ≤ 20% of direct dependencies with an outdated major version · C4 0 high or critical vulnerabilities (`npm audit`). Queries the npm registry. | auto with network |
| **Coupling** | Modularity | C1 0 cycles · C2 X (MMo-1-G) ≥ 0.90 · C3 Propagation Cost (DV8) ≤ 20% · C4 ≤ 10% unused dependencies (`depcheck`). | auto |
| **Data model** | Modularity, Analyzability | C1 every table has a primary key and every relation is a declared foreign key · C2 normalization consistent with access (≤ 3NF) · C3 integrity constraints declared in the schema · C4 indexes on foreign keys and on the fields the code filters by · C5 no unjustified redundancy or inconsistent types · C6 the declared ER model matches the implemented schema. | mixed: C1, C3, C4, C6 automatic; C2 and C5 are suggestions |
| **Contracts** | Modularity, Testability | C1 machine-readable contract (OpenAPI…) · C2 0 Spectral errors · C3 contract covers ≥ 90% of routes · C4 input validation consistent with the contract. | mixed |
| **Observability** | Analyzability | C1 ≥ 80% of critical events logged (approximated with `catch` blocks that log or delegate to a handler that logs) · C2 structured logger and no `console.*` · C3 centralized error handling · C4 health check, metrics or traces. | mixed |
| **Tests** | Testability | C1 0 CWE-478/484/1075 violations · C2 tests exist and pass · C3 line coverage ≥ 70% · C4 branch coverage ≥ 50%. | auto (requires running the tests) |
| **Configuration** | Modifiability | C1 0 network literals (URL, IP, port) · C2 no duplicated literals per S1192 · C3 external configuration (`.env.example` or configuration module). | auto |

### Notes per point

- **Layers.** Each file's layer is deduced from the name of its directories (`controllers`, `services`, `models`…), using the
  table in `rubric.json`. It can be replaced by a `.layers.json` inside the app. Two situations do not resolve themselves and
  leave C2 pending: **(a)** zero inter-layer dependencies (typical with dependency injection: nothing imports anything, so
  there is no structural evidence) and **(b)** a violation that depends on an ambiguous directory such as `domain` or `core`, which
  depending on the architecture may be business logic or the application core.
- **Configuration C2.** Uses SonarQube rule S1192 (`no-duplicate-string` in `eslint-plugin-sonarjs`): threshold of 3
  repetitions, minimum length of 10, no literals made only of word characters and no `application/json`. Values
  verified against the plugin's code. It is an **absolute** rule: it does not depend on the other evaluated applications.
- **DL and PC (DV8).** They are computed on a dependency matrix built from the module graph, with the dependency
  type `Import`. DV8 does not analyze JavaScript or TypeScript by itself. The values **without isolated files** are used,
  because DV8 reports 100% DL when there is an isolated file (for example `vite.config.js`) and that distorts the result.
  Both values are recorded.
- **Unhealthy Inheritance.** Needs a base class defined in the project. If no class extends another class of the project
  (all inherit from `Error`, for example) the count is 0. If an own hierarchy exists, it stays pending and is reviewed by hand
  with DV8's two criteria: a parent that depends on its child, or a client that depends on both.
- **Coverage.** With Jest, `coverage-summary.json` is read, also counting the files that no test loads. With Node's native
  runner (`node --test`) it is run under `c8 --all`, which also instruments the files that no test loads, so
  lines and branches have the full denominator. If `c8` is not installed it falls back to `--experimental-test-coverage`
  (unloaded files add 0% of lines and their branches do not enter the denominator).
- **Code duplication.** `jscpd` (≥ 5 lines and ≥ 50 tokens, excluding tests and `node_modules`) gives the percentage of duplicated
  lines and the largest clones. It is **informational**: it is shown in the Cyclomatic complexity sheet but does not change any
  level; the reference threshold (5%) is in `rubric.json` (`thresholds.duplication`).
- **Cognitive complexity** (SonarSource, approximate): +1 per control structure, plus the nesting level, and +1 per
  sequence of logical operators. Nested functions are measured separately. Informational; reference of 15 per function.
- **Probable dead code.** Production files that no other file imports and that are not entry points (`index`, `server`,
  `app`…). Informational; listed in the Coupling evidence.
- **Supplementary indicators** (`supplementary.json` and section of `profile.md`; informational, not scored): test
  quality (cases without assertions, test LOC / production LOC, integration tests), documentation (% of functions with
  JSDoc, README topics), frontend (large components, components with many props, hooks without a dependency array,
  frontend tests), static security (`eval`, literal credentials, raw SQL built by interpolation or concatenation) and
  schema-contract consistency (% of the table columns that appear, ignoring case and `_`, as a property in the OpenAPI). The reference thresholds
  are in `thresholds.supplementary` of `rubric.json`.
- **Data model.** Evaluated over a relational schema that is extracted statically (`relational_schema.py`) from, in order of
  preference: SQL files (`*.sql`: migrations, `schema.sql`, Prisma `migration.sql`), Sequelize migrations (`queryInterface.createTable`,
  `addColumn`, `addConstraint`, `addIndex`; the `down` half is ignored) and Sequelize models (`sequelize.define`, `Model.init`,
  `belongsTo`, `hasMany`, `hasOne`, `belongsToMany`). A table is decided entirely by the first source that defines it, and every element of
  the normalized schema records its `source`; lower sources only add tables the higher ones do not mention. If no relational schema is found
  the *Data model schema* artifact is missing and the point is **not evaluable**. The criteria:
  - **C1** (automatic). Every table has a primary key, and no column named like a reference (`*_id`, `*Id`) lacks a foreign key. Such columns are reported
    as *implicit relations*; a table's own single-column primary key is not one.
  - **C2** (suggestion). Normalization up to 3NF consistent with how the code accesses the data. The program suggests `true` when there are no repeating
    groups (`phone1`, `phone2`), no denormalized copies of a referenced column (`product_name` next to `product_id`) that the README or the ER document
    leaves unjustified (a word such as *snapshot* or *denormalized* near the column name, list in `relational.denormalization_words`), and no
    reads inside loops (N+1). 3NF itself is not verified: a person decides.
  - **C3** (automatic). At least `thresholds.data_model.constraints_min_pct` of the non-primary-key columns declare some constraint (`NOT NULL`, `UNIQUE`,
    `CHECK` or `FOREIGN KEY`), and no money-like column (name matches `relational.money_name_pattern`) uses a floating-point type (`FLOAT`, `REAL`,
    `DOUBLE PRECISION`; use `NUMERIC`). Natural keys such as `email` without `UNIQUE` are listed as evidence but do not change the verdict. Sequelize `validate`
    rules live in the application, not in the database, and do not count.
  - **C4** (automatic). Every foreign key column set is the leading part of an index, unique constraint or primary key (PostgreSQL does not index foreign
    keys by itself), and at most `thresholds.data_model.unindexed_queries_max_pct` of the distinct query filters have no index whose first column is one
    of the filtered fields. Filters come from the AST (`where` of Sequelize `findOne`, `findAll`, `findAndCountAll`, `count`, `update`, `destroy`…, including
    `Op.or` / `Op.and` branches) and from the `WHERE` clause of raw SQL strings. Filters by the primary key alone are not counted. A filter whose model or
    table cannot be resolved, or that is built dynamically, is not counted (`queries_unresolved`, `dynamic_queries` in the metrics).
  - **C5** (suggestion). The same column name (ignoring case and `_`) never has different type families in different tables, there are no tables with
    identical columns and the naming convention is not mixed (snake_case with camelCase).
  - **C6** (automatic). The Mermaid `erDiagram` in `docs/entity-relationship-model.md` matches the schema: the same entities (names compared ignoring case,
    `_` and plurals), the same attributes in each entity, the same primary-key and foreign-key markers, and a relationship for each foreign key with the
    "one" side on the referenced table. Differences in attribute types and in optionality (zero vs. one) are reported but are not mismatches. If the file is
    missing or has no `erDiagram`, C6 fails and the *Entity-relationship model* artifact is recorded as absent.
- **Technologies (C2).** The supported majors of Node, React and Express are queried from `endoflife.date` on every run with a
  network; Mongoose and MongoDB use the `rubric.json` table. The source is written in the criterion.

## Data model on a real database

With `--mongo` (environment variable `MONGO_URI`, without a database name) `mongo_analysis.py` starts the backend against a database
`eval_<run>`, exercises it with the acceptance gate and with `seed_api.py` (the same 25 users and their orders in all
apps), and dumps with `mongo_schema.js` what MongoDB Compass shows: observed schema, indexes, index usage, validators, document
size, array length and relations. Then it drops the database. The criteria that use that data:

- **C1** requires relations to be declared in the model (`ref` or subdocument). If in the data a String field contains the
  `_id`s of another collection, the relation is implicit and C1 is not met. Orphans (values without a target) are reported.
- **C3** requires `required` in all schemas and at least 50% of fields to have some constraint (`required`, `enum`,
  `min`, `max`, `match`…).
- **C4** requires an index on the relation fields of each collection and on the fields the code uses as filters in its
  queries (extracted from the AST). Redundant indexes (prefix of another) and unused ones are reported.
- **C2** (suggestion): references that resolve with `populate`, no reads inside loops (N+1), bounded arrays
  (≤ 1000 elements) and documents ≤ 16 KB.
- **C5** (suggestion): conflicting types between schemas or mixed in the database, identical schemas and mixed naming convention
  (snake_case and camelCase).

Without a real database (without `--mongo`) the static analysis of the code is used. The thresholds are in `thresholds.data_model` of `rubric.json`.

## Ranked risk list

In addition to the dashboard above, to see at a glance where maintainability is most at risk, `profile.md` and `report.md` condense the 11 points into a risk map:

- **Traffic light** per point: 🟢 Meets, 🟡 Partial, 🔴 Fails, ⚪ undecided (pending criteria).
- **Points at stake**: how many of the 100 overall points the point can still cost. A point controls `weight / (points in that
  subcharacteristic)` of each subcharacteristic it feeds, so a point that is the only one feeding a heavy subcharacteristic weighs more.
  The worst case (lowest score of the range) is used for ranking, so pending points are not hidden behind a "?".
- `profile.md` lists the points of one app, highest risk first. `report.md` adds a **heat map** (points × applications, riskiest rows
  first) and the top 3 risks per application. The same data is in `profile.json` under `risk`.

## Heuristics

Some criteria come with an automatic suggestion (data model C2 and C5, cohesion C3), described above. They **do not count** as a
result unless `--accept-heuristics` is passed; by default they only guide the person doing the review.

Data model C1, C3, C4 and C6 are verifiable over the schema and count without accepting heuristics. Contracts C4 is
automatic: there is a contract, there is a validation library, at least 90% of the POST/PUT/PATCH routes validate their input and the fields they
validate (zod, Joi, yup, express-validator) exist as a property in the contract. Hierarchies C3 applies DV8's rules to the import
graph. Observability C1 includes authentication and writes in addition to the `catch` blocks. Cohesion also reports DV8's IL
(`dv8_metrics.py` computes it) and Coupling reports the cliques.

## Traceability

Each run leaves in `results/<app>/`: `profile.md` and `profile.json` (result), `scorecard.json` and `scorecard.csv` (the 11 points
with their criteria and evidence), `traceability.csv`, `metrics.json` (raw evidence), `detected_layers.json` (each
file's layer and which directory decided it) and the `dv8/` folder with the matrix and the metrics. `results/environment.json` records
the versions used.
