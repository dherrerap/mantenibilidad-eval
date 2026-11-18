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
| Data model schema (SQL files, Sequelize migrations or models) | Core | Data model design | Structural |
| Entity-relationship model (`docs/R2/entity-relationship-model.md` after r2, else `docs/entity-relationship-model.md`) | Complementary | Data model design (C6) | Declarative |
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

How the framework applies it (`inventory_artifacts` in `evaluator/artifacts.py`; the table itself is in `rubric.json` under `artifacts`,
so the mapping is editable):

- **Core artifact missing** → the points it feeds are **not evaluable**: no level, no score, and they are excluded from the subcharacteristic
  averages. They are shown as ▨ "not evaluable", never as "Meets".
- **Complementary artifact missing** → a finding in `profile.json` / `profile.md`, ranked on the IEEE Std 1028 scale used for the
  points: *Marginal*, or *Critical* for the test suite (`"absence": "high_finding"` in the table). The confidence of each affected point
  drops: `high` (nothing missing), `medium` (one missing), `low` (two or more). A Critical finding also raises the point's severity to
  *Critical*, whatever its level, and forces red in the dashboard.
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

Layers additionally uses percentage thresholds (see below).

The severity of each point follows the anomaly ranking of **IEEE Std 1028-2008, 6.8.3**: Meets → *Negligible*, Partial → *Marginal*,
Fails → *Critical*. The fourth rank, *Catastrophic*, is not used: 6.8.3(a) reserves it for anomalies whose consequences are loss of
life, failure of mission or very large economic or social loss and for which mitigation is not possible. *Critical* is the top rank in
use and is what forces red in the dashboard.

## Scores

- Each level is worth: Meets = 1, Partial = 0.5, Fails = 0.
- A subcharacteristic's score is the average of the points that feed it, times 100.
- The overall score is the weighted sum: Testability 30%, Analyzability 24%, Modularity 24%, Modifiability 22%.
- **Ranges.** A pending criterion (`ok = null`) is evaluated twice, as met and as not met. The point, the
  subcharacteristic and the overall score are then expressed as `minimum–maximum`. When everything is resolved, the range collapses to a
  single number and `complete = true`.

### Weight sensitivity

The weights come from a panel whose concordance is not significant (Kendall's W = 0.158, see [limitations](limitations.md)), so the
report (`report.md`, section *Weight sensitivity*; `_comparison/sensitivity.json`) scores every run again under other schemes
(`evaluator/sensitivity.py`):

| Scenario | Weights |
|---|---|
| `panel` | 30/24/24/22, the reference. |
| `uniform` | 25% per subcharacteristic. |
| `equal_points` | Plain mean of the evaluable points, without subcharacteristics: a point counts once however many subcharacteristics it feeds. |
| `without_<point>` | Panel weights with that point removed from every subcharacteristic (leave-one-out, 11 scenarios). |
| `sensitivity.weight_sets` | Optional sets in `rubric.json`, normalized to 1; for example each expert's own Borda weights. |

For each scenario the report gives every run's score and rank, Kendall's tau-b against the panel ranking, whether the best run is the
same, and whether the order of the levels and of the agents by mean score holds. Ranks use the midpoint of each score range. A
conclusion that holds only under the panel weights (for example "N3 is more maintainable than N1") depends on a weighting the panel
did not agree on, and has to be reported as such.

## The 11 points

The *Type* column indicates how it is decided: **auto** (no intervention), **mixed** (the program computes and a person confirms
or completes) or **manual**.

| Point | Subcharacteristics | Criteria | Type |
|---|---|---|---|
| **Layers** | Modularity | C1 at least 2 identifiable layers · C2 violations ≤ 5% of inter-layer dependencies (Meets at 0%, Partial up to 5%). Only presentation→business and business→data are allowed. | auto, with review if the evidence is ambiguous |
| **Cyclomatic complexity** | Modularity, Modifiability | C1 X ≥ 0.95 · C2 X ≥ 0.98, where X = 1 − (functions with CC > 20)/(total) · C3 ≤ 10% duplicated lines (CWE-1041). | auto |
| **Cohesion** | Modularity, Modifiability | C1 ≤ 5% of functions with fan-out > 5 · C2 DL (DV8) ≥ 60% · C3 checklist with no findings ("god" module, mixed responsibilities, fragmentation; not met when a module both defines routes and queries the database, or a frontend component exceeds 200 LOC) · C4 0 production files over 1000 LOC (CWE-1080). | mixed |
| **Hierarchies** | Modularity | C1 inheritance depth ≤ 7 · C2 ≤ 10 direct children · C3 0 Unhealthy Inheritance patterns. | auto |
| **Technologies** | Analyzability, Modifiability | C1 no deprecated packages · C2 runtime, framework and PostgreSQL supported (endoflife.date; table in `rubric.json`) · C3 ≤ 20% of direct dependencies with an outdated major version · C4 0 high or critical vulnerabilities (OSV). On the resolved versions and as of the reference date `--as-of`; dependency age in libyears is informational. Queries the npm registry and OSV. | auto with network |
| **Coupling** | Modularity | C1 0 cycles · C2 X (MMo-1-G) ≥ 0.90 · C3 Propagation Cost (DV8) ≤ 20% · C4 ≤ 10% unused dependencies (Knip) · C5 0 production files unreachable from every entry point (Knip, CWE-561). | auto |
| **Data model** | Modularity, Analyzability | C1 every table has a primary key and every relation is a declared foreign key · C2 normalization consistent with access (≤ 3NF) · C3 integrity constraints declared in the schema · C4 indexes on foreign keys and on the fields the code filters by · C5 no unjustified redundancy or inconsistent types · C6 the declared ER model matches the implemented schema. | mixed: C1, C3, C4, C6 automatic; C2 a suggestion; C5 not met when column types are inconsistent, a suggestion otherwise |
| **Contracts** | Modularity, Testability | C1 machine-readable contract (OpenAPI…) · C2 0 Spectral errors · C3 contract covers ≥ 90% of routes · C4 input validation consistent with the contract. Informational: runtime conformance of the responses to the contract (Prism, during the acceptance gate). | mixed |
| **Observability** | Analyzability | C1 ≥ 80% of critical events logged (approximated with `catch` blocks that log or delegate to a handler that logs, plus authentication and write functions that log or are covered by a request logger) · C2 structured logger and no `console.*` · C3 centralized error handling · C4 health check, metrics or traces (a parameterless route whose last segment is `health`, `ready`, `live`, `ping`, `status`, `metrics`…, so that `PATCH /orders/:id/status` does not count). | mixed |
| **Tests** | Testability | C1 0 CWE-478/484/1075 violations · C2 tests exist and pass · C3 line coverage ≥ 70% · C4 branch coverage ≥ 50% (not applicable, and left out, when the coverage report has no branches). Informational, with `--mutation`: mutation score (StrykerJS). | auto (requires running the tests) |
| **Configuration** | Modifiability | C1 0 network literals (URL, IP, port) · C2 no duplicated literals per S1192 · C3 external configuration (`.env.example` or configuration module). | auto |

### Notes per point

- **Layers.** Each file's layer is deduced from the name of its directories (`controllers`, `services`, `models`…), using the
  table in `rubric.json`. It can be replaced by a `.layers.json` inside the app. Two situations do not resolve themselves and
  leave C2 pending: **(a)** zero inter-layer dependencies (typical with dependency injection: nothing imports anything, so
  there is no structural evidence) and **(b)** a violation that depends on an ambiguous directory such as `domain` or `core`, which
  depending on the architecture may be business logic or the application core. A dependency on a module of such a directory that itself
  uses nothing of the presentation or data layers (domain errors, entities, policies) is a **shared core**, which every layer may use in a
  hexagonal or clean architecture: it is not a violation and is listed as `shared_core_dependencies`; only a "domain" module that reaches
  into the outer layers stays doubtful.
- **Cohesion C3.** A measured finding decides it as not met: a production module that defines HTTP routes and also runs database queries
  itself (SQL strings outside migrations or ORM calls; `routes_and_queries_in_one_file`), or a frontend component longer than
  `thresholds.cohesion.component_loc_max` (200, the default of SonarJS S138). Without them the program only suggests a value from the
  "god" module and fragmentation heuristics, because mixed responsibilities in general need reading the code.
- **Configuration C2.** Uses SonarQube rule S1192 (`no-duplicate-string` in `eslint-plugin-sonarjs`): threshold of 3
  repetitions, minimum length of 10, no literals made only of word characters and no `application/json`. The rule itself runs
  (`lint_metrics.js`, over the production files) and counts the repetitions **per file**, like SonarQube. A reported literal fails
  C2. C2 stays **pending** when ESLint did not run, and when it reports nothing but could not parse some file (a 0 is not proven
  then). It is an **absolute** rule: it does not depend on the other evaluated applications.
- **MMo-1-G (Coupling C2).** The numerator counts the modules whose outgoing coupling is bounded. It no longer counts the absence of
  dependency cycles: that is criterion C1 of the same point (CWE-1047), and counting it in both let a single defect lower two of the
  five criteria. ISO/IEC 25023 defines the denominator as the components *specified* as required to be independent; a generated
  application specifies no such set, so every module is used, which is the conservative reading. Modification declared under
  Clause 2(d) of the standard.
- **DL and PC (DV8).** They are computed on a dependency matrix built from the module graph, with the dependency
  type `Import`. DV8 does not analyze JavaScript or TypeScript by itself. The values **without isolated files** are used,
  because DV8 reports 100% DL when there is an isolated file (for example `vite.config.js`) and that distorts the result.
  Both values are recorded.
- **Unhealthy Inheritance (Hierarchies C3, CWE-1062).** Needs a base class defined in the project. If no class extends another class of
  the project (all inherit from `Error`, for example) the count is 0. If an own hierarchy exists, the framework applies DV8's two rules to
  the import graph: a parent that imports its child, or a client that imports both. It stays pending only when there is no dependency
  graph; a value in the manual review or in `dv8/dv8_manual.json` overrides the computed one.
- **Coverage.** With Jest, `coverage-summary.json` is read, also counting the files that no test loads. With Node's native
  runner (`node --test`) it is run under `c8 --all`, which also instruments the files that no test loads, so
  lines and branches have the full denominator. If `c8` is not installed it falls back to `--experimental-test-coverage`
  (unloaded files add 0% of lines and their branches do not enter the denominator).
- **Code duplication (CWE-1041).** `jscpd` (≥ 5 lines and ≥ 50 tokens, excluding tests and `node_modules`) gives the percentage of
  duplicated lines and the largest clones. It is **scored** as criterion C3 of Cyclomatic complexity, with the threshold of 10% that
  ISO/IEC 5055 publishes for CWE-1041 (`thresholds.duplication.pct_max`). Caveat recorded in `backing`: the standard sets 10% *of the
  instructions in each clone instance*, while `jscpd` reports the percentage of duplicated lines across the whole application, so the
  numbers coincide but the measurements do not. If `jscpd` did not run, C3 stays pending and the point's level becomes a range.
- **Cognitive complexity**: measured with SonarSource rule S3776 itself (`sonarjs/cognitive-complexity`); not measured if ESLint
  did not run. Informational; reference of 15 per function.
- **McCabe cross-check** (informational): the McCabe count of `ast_metrics.js`, which decides Cyclomatic C1/C2, is compared function by
  function with ESLint's `complexity` rule (`metrics.mccabe_eslint`: share of equal values and the X ESLint would give). Both count
  default parameters, `&&`/`||`/`??`, logical assignments, `case` and `catch` alike; ESLint also counts each optional chaining `?.`.
- **ASCMM weaknesses that no point scores** (supplementary indicators, group *ASCMM*; informational): CWE-1064 (functions with more than
  7 parameters, from the AST), and with ESLint + `eslint-plugin-sonarjs` CWE-480, CWE-570/571, CWE-783, CWE-1095 and CWE-1085 (functions
  whose commented-out lines exceed 2% of their lines). Each gives the count, its density per KLOC (ISO/IEC 5055, Annex C.1) and the
  reference of the standard. The rules of each weakness are in `lint.ascmm` of `rubric.json`; the rule-to-CWE mapping is ours.
  ESLint runs with its own configuration only: the app's `eslint.config.*` and its `eslint-disable` comments are ignored.
- **Structurally dead code (CWE-561).** Production files that Knip cannot reach from any entry point. Reachability is transitive: two
  files that only import each other are dead too. The entry points are Knip's own (package.json `main`, `bin` and the files its
  scripts run, such as `"migrate": "node src/data/migrateCli.js"`; Vite's `index.html`, Jest's test patterns and the other tools it
  recognizes) plus `dead_code.entry_points` (base names such as `index`, `server`, `app`) and `dead_code.entry_globs` (migrations and
  seeders, `*.config.*`) of `rubric.json`. Each directory with a `package.json` is analyzed as its own project. **Scored** as criterion
  C5 of Coupling, with the threshold of 0 that ISO/IEC 5055 sets for structurally dead code. The 5% allowance the same weakness gives
  to *logically* dead code is not applied, because unreachable statements inside a function are not detected.
- **Unused dependencies (Coupling C4)** come from the same Knip run, as do two informational counts: unused exports and dependencies
  used but not declared in `package.json`. C4 and C5 stay pending if Knip did not run.
- **Knip does not execute the app.** Knip normally imports the JS/TS configuration files of the tools it recognizes, which would run
  code written by the model. `knip_metrics.js` gives each plugin the package enables only its data configuration files (JSON, YAML,
  rc, `package.json`) and passes the JS/TS ones as entries, which are parsed like any source file; and Knip runs under
  `no_exec_guard.mjs`, which makes any import, `require` or `vm` evaluation of a file of the app fail. Load errors, if any, are in
  `metrics.json` (`knip.config_load_errors`).
- **Contracts C1 and the *Contract specification* artifact.** C1 is met only by an OpenAPI or Swagger document (`openapi*.json|yaml`,
  `swagger*.json|yaml`; the one of `docs/R2/` first), because C2–C4 and the runtime conformance need one. The artifact of Table 27 is
  wider: JSON Schema files and DTO modules also make it present, so an app with DTOs but no OpenAPI has the artifact and still fails C1.
- **Contract coverage (Contracts C3).** Each route gets its full path from the `app.use(prefix, router)` calls whose router resolves
  to a file of the app (imports, `require`, factories such as `createRouter(deps)`, nested routers). It matches a contract operation
  only with the same method and the same path, with parameter names ignored, alone or under the contract's base path (`servers[].url`,
  `basePath`). When a router's prefix cannot be resolved, a match of whole trailing segments is accepted for its routes, and the count
  of such routes is recorded (`routes_with_unresolved_prefix`). A route validates its input (C4) when its call contains a validation
  middleware or schema; `pool.query(`, `req.body(` and `JSON.parse(` do not count.
- **Hierarchies C2** counts the direct children of the project's own classes: twelve subclasses of `Error` or `React.Component` are
  not a wide hierarchy of the app.
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
    as *implicit relations*; a table's own single-column primary key is not one, and neither is the id of a polymorphic association: a
    `<x>_id` next to a discriminator (`<x>`, `<x>_type`, `<x>_table`…) where no table is named `<x>`, such as the `entity` + `entity_id` of an
    audit log, which points at a different table on each row and admits no foreign key (`polymorphic_references`).
  - **C2** (suggestion). Normalization up to 3NF consistent with how the code accesses the data. The program suggests `true` when there are no repeating
    groups (`phone1`, `phone2`), no denormalized copies of a referenced column (`product_name` next to `product_id`) that the README, the ER document
    and the design documents (`docs/**/*.md`) leave unjustified (a word such as *snapshot* or *denormalized* near the column name, list in `relational.denormalization_words`), and no
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
  - **C5** (automatic when it fails, suggestion otherwise). The same column name (ignoring case and `_`) with different type families in different
    tables is measured and decides C5 as not met (`type_conflicts`). Otherwise the program suggests `true` when there are no tables with identical
    columns and the naming convention is not mixed (snake_case with camelCase); whether a redundancy is justified is decided by a person or the judge.
  - **C6** (automatic). The Mermaid `erDiagram` of the ER model matches the schema. The model is the one of the latest documentation set
    (`docs/R2/entity-relationship-model.md`, or another `.md` of `docs/R2/` with an `erDiagram`; labels in `relational.doc_versions`), else
    `docs/entity-relationship-model.md`; the README is chosen the same way (`docs/R2/README.md` before the root one). It must match: the same entities (names compared ignoring case,
    `_` and plurals), the same attributes in each entity, the same primary-key and foreign-key markers, and a relationship for each foreign key with the
    "one" side on the referenced table. Differences in attribute types and in optionality (zero vs. one) are reported but are not mismatches. If the file is
    missing or has no `erDiagram`, C6 fails and the *Entity-relationship model* artifact is recorded as absent.
- **Technologies: resolved versions and reference date.** Every criterion looks at the version each direct dependency *resolves to*, not at
  the lower bound of its declared range: the app's `package-lock.json` when it pins every direct dependency, otherwise the lockfile npm
  generates with the registry as it was on the reference date (`npm install --package-lock-only --ignore-scripts --before=<as_of>`).
  Everything that changes with time is computed as of that date (`--as-of YYYY-MM-DD` in `cli.py evaluate`, `as_of` in `experiment.json`;
  default: the evaluation date): the latest version of a dependency is the highest stable one published by then (C3); the vulnerabilities are
  the OSV advisories (the GitHub Advisory Database that `npm audit` uses) for every package of the lockfile, transitive ones included,
  that were in the database and not withdrawn by then (the later of the publication date and GitHub's review date, since an advisory
  can carry the earlier date of its CVE and enter the reviewed database weeks later), with severity HIGH or CRITICAL (C4; a malicious-package record counts as critical); and
  the supported runtimes are the endoflife.date cycles released and not yet at end of life by then (C2). **Fix `as_of` to the generation
  date of the experiment**: a re-evaluation months later then gives the same versions and the same advisories. A dependency whose version
  was published after `as_of` means the date is earlier than the app: the finding warns and C3 stays pending.
- **Dependency age (libyear, informational).** Cox, Bouwers, van Eekelen and Visser, *Measuring Dependency Freshness in Software Systems*
  (ICSE 2015): for each direct dependency, the years between the release of the version in use and the release of the latest version as of
  `as_of`; the point reports the sum and the mean over the production dependencies (`metrics.libyear`), and the devDependencies apart.
  It changes no level: the study proposes the measure, not a cut-off.
- **Technologies (C2).** The supported majors of Node, React, Express and PostgreSQL are queried from `endoflife.date` on every run with a
  network (`supported_runtimes.eol_products` in `rubric.json`); Sequelize and `pg` use the `rubric.json` table, and so does everything when offline.
  The PostgreSQL version of the evaluated app is the major in the image tag of its `docker-compose.yml`. The table entries for PostgreSQL, Sequelize and
  `pg` are unverified working assumptions (`supported_runtimes.unverified`); the source is written in the criterion.

## Data model on a real database

With `--postgres` (environment variable `PG_ADMIN_URL`, the connection string of a role that can create databases; without it, a disposable server
that `pg_temp.py` starts for the whole batch from the local PostgreSQL binaries, see below) `pg_analysis.py` creates a
database `eval_<run>`, starts the backend against it (`DATABASE_URL`, `PORT`), exercises it with the acceptance gate and with `pg_seed.py` (the same 25
users and their orders or seat purchases in all the apps of a domain; the gate is skipped on an app that already implements
`r2-additional-requirements.md`, because its suites cover the original requirements), reads its catalog with `pg_schema.js` through the `pg` package (`information_schema` for tables and columns;
`pg_catalog` for constraints, foreign keys, indexes and `pg_stat_user_indexes` for index usage) and drops the database. `pg_schema.js` refuses to
create, read or drop any database whose name does not match `eval_[a-z0-9_]+`, and `PG_ADMIN_URL` itself is not passed to the evaluated backend. The
catalog is saved in `results/<run>/pg_schema.json` and replaces the static schema for these criteria:

*Temporary server.* When `PG_ADMIN_URL` is not set, `cli.py evaluate --postgres` looks for `initdb` and `pg_ctl` (`PG_BIN`, the `PATH`, then the usual
install folders, highest major first), creates a cluster in a new temporary folder, starts it on `127.0.0.1` and a free port with a superuser
`evaluator` whose random password exists only in memory (scram-sha-256), uses it for every app of the batch and stops and deletes it at the end.
Docker is not needed and no existing server or database is touched. `python pg_temp.py` checks that it can start one.


- **C1** counts tables without primary key and `*_id` columns without a foreign key in the real database.
- **C3** counts the constraints that PostgreSQL actually has (`NOT NULL`, `UNIQUE`, `CHECK`, foreign keys) and the column types.
- **C4** looks for FK columns and query filters in the real indexes. Redundant indexes (prefix of another) and unused ones (`idx_scan = 0`) are
  reported but do not change the level: with 25 users the planner and the statistics are not representative.
- **C6** compares the ER diagram against the real schema.
- **C2** and **C5** (suggestions) read the real schema too; the queries still come from the code.

Without a real database (without `--postgres`, if the backend does not start, or if the database ends up with no tables) the static schema of the code is
used, as described above. The thresholds are in `thresholds.data_model` of `rubric.json`.

## Test quality and runtime contract conformance (informational)

Two measures look at behaviour instead of structure. Neither changes a level: there is no published cut-off for either, and one has
to be calibrated on the experiment's data before it can score.

- **Mutation score (Tests, `--mutation`).** Coverage says which lines the tests run; mutation testing says whether the tests would
  notice if those lines were wrong. StrykerJS plants small faults (mutants: a `>=` turned into `>`, a condition forced to `true`…) in the
  production code of every package with a `test` script and runs the package's own `npm test` against each one, in a sandbox copy (the
  app is not modified). Score = mutants detected (Killed, Timeout) / valid mutants (detected + Survived + NoCoverage), as Stryker defines
  it; the surviving mutants are listed as evidence (`metrics.json` → `mutation`). It runs the app's tests once per mutant, so it needs
  `--run-tests`, is opt-in and slow: bounded by `mutation.max_minutes_per_package` in `rubric.json` (30 by default), and StrykerJS 10
  needs Node.js 22 or later. Configuration, migrations, seeders, type declarations and test files are not mutated.
- **Runtime conformance to the contract (Contracts).** The static criteria tell whether a contract exists and whether its paths match the
  routes in the code; this tells whether the responses the running API returns are the ones the contract documents. When the acceptance
  gate runs (`cli.py evaluate --postgres`, or `run_experiment.py` with Docker), `acceptance_check.py --app` sends the suite through a Prism
  proxy (`contract_conformance.py`) that validates every exchange against the app's contract (the one of `docs/R2/` first). A call
  conforms when its route is documented, its status code is declared and its body matches the schema; the requests the suite makes
  invalid on purpose (to check the 400s) are counted apart and do not lower it. Result: `contract_conformance.json`, read by the scoring
  like the live database.

## ISO/IEC 5055 weaknesses and their density

ISO/IEC 5055 measures maintainability (ASCMM) by counting the occurrences of its weaknesses, and its Annex C.1 proposes dividing that
count by the size of the application to compare applications of different size. The levels of this framework decide each weakness
as pass/fail; next to them, every run reports the occurrences of the 22 weaknesses it detects and their **density per KLOC of production
code** (`profile.json` → `ascmm`, a section of `profile.md`, and in `report.md`, `_comparison/comparison.md` and the `kloc`,
`ascmm_*` columns of `comparison.csv`). It is informational: no level uses it.

- **Same values as the levels.** The count of each scored weakness is the one its point measured (for example the switches without
  `default` of Tests C1, the cycles of Coupling C1, the functions over CC 20 of Cyclomatic), so a density can never contradict a level.
  The informational ones (CWE-480, 570/571, 783, 1064, 1085, 1095) come from the supplementary indicators.
- **What one occurrence is** depends on the weakness (a function, a file, a cycle, a clone instance, a literal…); the profile says it per
  row. The total, like the ASCMM of the standard, adds them up.
- **Size.** The standard normalizes by Automated Function Points, which the framework does not compute; KLOC of production code (test files
  left out) is the substitute. Applications generated from N1 and from N3 differ in size, so **compare densities, not counts**.
- **Not measured.** A weakness whose criterion is pending, whose tool did not run or whose point is not evaluable shows `n/a`; the totals
  are then a lower bound (`≥`).

## Ranked risk list

In addition to the dashboard above, to see at a glance where maintainability is most at risk, `profile.md` and `report.md` condense the 11 points into a risk map:

- **Traffic light** per point: 🟢 Meets, 🟡 Partial, 🔴 Fails, ⚪ undecided (pending criteria).
- **Points at stake**: how many of the 100 overall points the point can still cost. A point controls `weight / (points in that
  subcharacteristic)` of each subcharacteristic it feeds, so a point that is the only one feeding a heavy subcharacteristic weighs more.
  The worst case (lowest score of the range) is used for ranking, so pending points are not hidden behind a "?".
- `profile.md` lists the points of one app, highest risk first. `report.md` adds a **heat map** (points × applications, riskiest rows
  first) and the top 3 risks per application. The same data is in `profile.json` under `risk`.

## Heuristics

Some criteria come with an automatic suggestion (data model C2 and C5, cohesion C3; C5 and C3 only when no measured finding decides them), described above. They **do not count** as a
result unless `--accept-heuristics` is passed; by default they only guide the person doing the review.

Data model C1, C3, C4 and C6 are verifiable over the schema and count without accepting heuristics. Contracts C4 is
automatic: there is a contract, there is a validation library, at least 90% of the POST/PUT/PATCH routes validate their input and the fields they
validate (zod, Joi, yup, express-validator) exist as a property in the contract. Hierarchies C3 applies DV8's rules to the import
graph. Observability C1 includes authentication and writes in addition to the `catch` blocks. Cohesion also reports DV8's IL
(`dv8_metrics.py` computes it) and Coupling reports the cliques.

## Source of every threshold

`rubric.json` carries a top-level `backing` map that states, for every threshold and weight, where its value comes from, keyed by its
dotted path. The `type` field grades the strength of the backing: `normative_exact` (the value equals the default published by
ISO/IEC 5055), `normative_alternate` (the standard publishes a default and this rubric uses another, which ISO/IEC 5055 permits
provided the alternate threshold is set before the analysis), `normative_zero_count` (ISO/IEC 5055 scores the weakness by counting
occurrences, so requiring zero is the reading consistent with Clause 9), `function_only` (ISO/IEC 25023 supplies the measurement
function but no cut-off, because its Scope states that it "does not assign ranges of values of the measures to rated levels or to
grades of compliance"), `tool_parameter` (the value comes from a tool's rule) and `own_calibration` (no source among the standards of
this study, declared under ISO/IEC 25023 Clause 2(e)). Only ISO/IEC 5055 supplies numeric thresholds; ISO/IEC 25010 supplies the
quality model only and IEEE Std 1028 the review process only. `backing` also records the coverage of the 29 weaknesses of the
Automated Source Code Maintainability Measure (`_coverage_ascmm`), the conformance statement for ISO/IEC 25023 Clause 2
(`_conformance_25023`, including the exclusions and their rationale) and the one for IEEE Std 1028 (`_conformance_1028`). The
evaluator's tests fail if a threshold has no backing entry or if a `normative_exact` value drifts from the standard's default.

## AI token consumption

Besides the static profile, each application has an **effort indicator**: the tokens the generator agent consumed in two phases of its
life, measured with `token_usage.py` from the agents' own usage records (procedure in [generating-apps.md](generating-apps.md)).

| Phase | What it measures |
|---|---|
| **initial** | Tokens to create the application from `technical-<level>.md` + `requirements-<domain>.md` (`combiner-prompt.md`). |
| **r2** | Tokens to implement `r2-additional-requirements.md` on top of that same application, in a new session (`r2-prompt.md`). |
| **R2 / initial** | `total_tokens(r2) / total_tokens(initial)`: how much the change costs relative to building the application. |

Each phase adds every agent session devoted to that app and phase (subagents included; an orchestrating session is not attributed to any
app). The counts are normalized so that agents are comparable:

| Field | Definition |
|---|---|
| `input_tokens` | All input tokens processed, **including** the cache reads and writes (Claude: `input + cache_creation + cache_read`; Codex: `input_tokens`, which already includes `cached_input_tokens`). |
| `cache_read_tokens`, `cache_write_tokens` | Part of `input_tokens` read from or written to the prompt cache. |
| `output_tokens` | Generated tokens, **including** reasoning/thinking; `reasoning_tokens` is that part when the source reports it. |
| `total_tokens` | `input_tokens + output_tokens`. This is the figure of the report and of the R2 / initial ratio. |
| `requests` | Model calls (Claude: distinct assistant messages; Codex: `token_count` events). |

The tokens are **not part of the maintainability score** and do not change any decision point: they are reported next to it
(`report.md`, section *AI token consumption*; `_comparison/comparison.csv`, columns `tokens_*`) so that the score can be read against the
effort. The working hypothesis is that a more maintainable application at the end of phase initial needs fewer tokens in phase r2, in
absolute terms and relative to its creation; the framework provides the data to test it, not the conclusion.

## Traceability

Each run leaves in `results/<run>/`:

| File | Content |
|---|---|
| `profile.md`, `profile.json` | Result: profile, ranges, risk list, dashboard data and the ISO/IEC 5055 occurrences (`ascmm`). |
| `scorecard.json`, `scorecard.csv` | The 11 points with their criteria, metrics and evidence. |
| `traceability.csv` | Design decision → weakness → subcharacteristics → level → evidence. |
| `metrics.json`, `meta.json` | Raw evidence of the collection and the identity and options of the run; `rescore` works from them. |
| `manual.json` | The manual review and DV8 values the last scoring used. |
| `supplementary.json`, `artifacts.json` | Supplementary indicators (ASCMM group included) and input artifacts (Table 27). |
| `risk_dashboard.html`, `.md`, `.json` | The risk dashboard (Table 29). |
| `detected_layers.json` | Each file's layer and the directory that decided it. |
| `manual.template.json`, `manual_review.md`, `manual_review.draft.json` | Every pending criterion, and the review guide with evidence and suggestions. |
| `ast.json`, `depcruise.config.json`, `lint_raw.json`, `lint_request.json`, `jscpd/`, `knip/`, `mutation/` | Raw outputs of ts-morph, dependency-cruiser, ESLint, jscpd, Knip and StrykerJS (`mutation/` only with `--mutation`). |
| `dv8/` | The DV8 matrix and its metrics (`dv8_metrics.json`; `dv8_manual.json` for a human review). |
| `token_usage.json` | Tokens per phase and per session, with the source file of each. |
| `acceptance.json`, `contract_conformance.json`, `pg_schema.json`, `seed.json` | Only with the acceptance gate / `--postgres`: functional result, runtime conformance to the contract (Prism) and catalog of the live database. |
| `judge.json` | Only with `--judge`: the judge's decisions, votes and audit sample. |

`results/environment.json` records the versions used, the options and the reference date `as_of`; `results/_comparison/` has
`comparison.csv`, `comparison.md` and `sensitivity.json`.
