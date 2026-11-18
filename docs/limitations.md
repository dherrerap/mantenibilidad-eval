# Limitations

What the framework does **not** guarantee. Cite them alongside any result.

## Scope

- **PERN applications only** (PostgreSQL, Express, React, Node) with `backend/` and `frontend/` folders, each with its own `package.json`. Other
  structures require adjusting `ast_metrics.js` and the package detection. Results from the MERN pilot (EXP-01, tag `v0.1.0-mern`) were measured with
  a different data model rubric and are not comparable with PERN results criterion by criterion.
- **It does not evaluate whether the application works.** Without the acceptance gate a high score may correspond to a broken app. The gate
  (`acceptance_check.py`) runs in two ways: `run_experiment.py` starts PostgreSQL from the app's `docker-compose.yml` (needs Docker and Docker
  Compose v2; without them it is skipped and says so), and `cli.py evaluate --postgres` runs it against a disposable database of the server in
  `PG_ADMIN_URL` or, without it, of a temporary server started from the local PostgreSQL binaries (`pg_temp.py`). Without either, nothing in the
  profile tells whether the app works. It is a maintainability measure, not a correctness one.
- **The gate covers the original requirements only** (`requirements-ecommerce.md` or `requirements-cinema.md`, chosen by the domain).
  The additional requirements of phase r2 change some of its rules (prices, shipping, roles), so `run_experiment.py` runs it right
  after phase initial and skips it on a project that already implements r2. There is no acceptance suite for r2 yet. The 5-minute
  expiry of the cinema seat locks is not checked (it would take 5 minutes).
- **A single run per combination.** With one run per level there is no statistical basis to claim that one level beats
  another. Differences of a few points are within the margin left by the pending criteria.
- **The result is a range** as long as there are pending criteria. The ends are bounds, not estimates.

## Measurement

- **Layers by directory name.** It is a heuristic (names in `default_layers` of `rubric.json`; an app can ship a `.layers.json`). An app that organizes its layers with other names, or that connects them
  through dependency injection, gets "pending" and not an automatic result. Ambiguous directories (`domain`, `core`,
  `entities`) also leave the criterion under review, except when the module depended on uses nothing of the presentation or data layers
  (a shared core, not counted as a violation). That rule is structural: a "domain" module with no outer dependencies that still holds
  business logic a data module should not call is not detected.
- **DL and PC on a derived matrix.** DV8 does not analyze JavaScript or TypeScript. The matrix comes from the `dependency-cruiser`
  graph, with a single dependency type (`Import`), and the values may differ from those of a native analysis.
  With projects of fewer than 100 files they are sensitive to each dependency.
- **Unhealthy Inheritance** is decided with DV8's two rules applied by the framework to the import graph and the project's own classes
  (a parent that imports its child, or a client that imports both), not with DV8's detection: `arch-issue` needs inheritance
  edges and, for other detectors, git history, which the evaluated applications do not have. The **cliques** are also
  computed on the graph (strongly connected components), not with DV8.
- **Coverage with `node --test`** is measured with `c8 --all`. If `c8` is not installed, Node's native coverage is used, which
  overestimates branches because the files that no test loads do not enter the denominator.
- **Duplication (jscpd)** is now scored (Cyclomatic complexity C3) but detects textual clones by tokens only; it does not see semantic
  duplication. The 10% threshold is the default ISO/IEC 5055 publishes for CWE-1041, but the standard applies it to the instructions of
  each clone instance while `jscpd` reports duplicated lines across the whole application: the number is the standard's, the
  measurement basis is not. It is also looser than the 5% it replaced.
- **Duplicated-literal threshold (Configuration C2, S1192).** Its parameters (3 repetitions, 10 characters) come from a widely used
  external rule, SonarQube's, not from our own calibration study, and CWE-1052 publishes no numeric threshold.
- **Cognitive complexity** comes from SonarSource's own rule (S3776 in `eslint-plugin-sonarjs`) and stays informational.
- **ESLint parses less permissively than ts-morph.** A file it cannot parse is listed in `metrics.json` (`lint.parse_errors`) and its
  S1192, S3776 and ASCMM reports are missing: a count of 0 is then left pending (C2) or n/a (ASCMM), while a reported occurrence still
  counts. The McCabe count and the other AST measures still see that file.
- **The ESLint indicators of ASCMM weaknesses are informational, and their mapping is ours.** ISO/IEC 5055 names no tool: which rules
  stand for CWE-480, 570/571, 783, 1085 and 1095 (`lint.ascmm`) is a decision of this framework. CWE-783 counts `&&` mixed with `||`
  without parentheses, which is a risk of a precedence error, not always an error. CWE-1095 is partial: S2310 reports plain
  assignments to a `for` counter (`i = …`) but not `i++` or `i += …` in the body, nor updates of a `while` condition. CWE-570 and 571
  are counted together. CWE-1085 relates commented-out *lines* to the function's lines, where the standard relates instructions.
- **Dead code (CWE-561)** is scored (Coupling C5) over the production files that Knip cannot reach from any entry point, which is the
  *structural* half of the weakness, for which ISO/IEC 5055 sets the threshold at 0. Unused exports are reported but not scored, and
  unreachable statements inside a function are not detected, so the 5% the standard allows for *logically* dead code is not evaluated.
  A file is only reachable through an entry point Knip knows (package.json `main`, `bin` and scripts, the tools it recognizes, and the
  `entry_points` / `entry_globs` of `rubric.json`): a file run only from a Dockerfile, a Procfile or a tool Knip does not recognize is
  counted as dead until it is added to `entry_globs`. Files outside every package directory are not analyzed.
- **Knip reads the tools' JS/TS configuration files as source, without running them** (`knip_metrics.js`, `no_exec_guard.mjs`): their
  imports count, but whatever a configuration computes at run time (entries built in a loop, a Jest `projects` list returned by a
  function) is not seen. Without the app's `node_modules` (`--skip-tests`) Knip cannot map a binary to its package, so it reports a
  devDependency that a script runs (`jest`, `vite`) as unused. This only matters with `include_devdependencies` on (off by default):
  then such a devDependency counts as used when its binary has the package's name.
- **Data model C2/C5 suggestions and contracts C4** are heuristics over the code and schema text (repeating groups, columns that copy a
  column of the referenced table, type names, validation middleware names). C2 does not verify third normal form: it only looks for the symptoms listed
  in `docs/methodology.md`. They do not compare the schema with the contract field by field. C5 is decided automatically only when column types
  conflict; a justified or unjustified redundancy stays a judgment.
- **Cohesion C3 measured findings are proxies.** "Routes and queries in one module" sees SQL strings and ORM calls, not a query hidden behind a helper
  in another file; "component over 200 LOC" uses the length of a function that returns JSX. A long component that is still cohesive is reported as
  a finding: override it in `manual_review.json` if so.
- **Supplementary indicators** are heuristics over the code text and are not scored. "Without assertions" only recognizes
  `assert`, `expect` and `should`; credential detection looks at the variable name; the SQL check only sees a template
  literal with `${}` or a `+` concatenation passed as the first argument of `query`, `raw`, `execute` or `unsafe`, and ignores interpolated constants
  (literals, ternaries of literals, a module-level `const` string) but not parameters or values it cannot trace; the prop count of a component that receives `props` without
  destructuring is approximate. Dependency licenses are not checked. Mutation testing (`--mutation`) and unused exports (Knip) are
  reported elsewhere, also without scoring.
- **Observability C1** is a proxy: critical events are `catch` blocks, functions that use `bcrypt`/`jwt`/`passport`
  (authentication) and those that write with Sequelize (`save`, `create`, `bulkCreate`, `update`, `destroy`, `upsert`…; raw `INSERT`/`UPDATE`
  statements are not recognized). A function counts as logged if it
  calls a logger or if the app has a request logger (`morgan`, `pino-http`…). It does not tell whether the message is useful.
- **The OpenAPI contract is a deliverable since this version of the prompt** (`specs/combiner-prompt.md`, and `docs/R2/openapi.yaml` in
  `r2-additional-requirements.md`). Contracts C1 is mandatory, so applications generated with an earlier prompt, which did not ask for it,
  fail that point and **are not comparable** with the ones generated after it: generate every application of an experiment with the same
  prompt.
- **The mutation score is informational and partial.** StrykerJS's command runner runs the whole suite per mutant, without per-test
  coverage, so an untested mutant appears as Survived rather than NoCoverage, and the run stops at `mutation.max_minutes_per_package`
  (the package is then reported as not measured). Only the packages with a `test` script are mutated. There is no published cut-off for
  the score, which is why it does not score.
- **Runtime contract conformance only sees what the acceptance suite calls.** The suite covers the original requirements of the domain,
  not every endpoint, so a route it does not call is neither confirmed nor refuted; and it only runs with the gate (`--postgres` or
  `run_experiment.py` with Docker). Prism 5.14 (the last one that runs on Node 22) validates against OpenAPI 3.0/3.1 and Swagger 2.
- **Technologies** is fixed at the reference date `as_of` (resolved versions, latest version, advisories, supported runtimes), with three
  exceptions that are today's data: the **deprecation** of a version (npm does not date it), the **severity** of an advisory (OSV keeps the
  current one, which GitHub may have revised) and the advisories OSV did not have when it was queried. An advisory counts from the later of
  its publication and its GitHub review (`github_reviewed_at`); one without that field that entered the database after `as_of` with an
  earlier publication date is still counted. "Latest version as of `as_of`" is
  the highest stable version published by then, which may differ from the `latest` dist-tag of that day (a tag on an older line). The app's
  own lockfile wins over the reference date when it pins every direct dependency, because it is what the agent installed. OSV receives
  the names and versions of the installed packages, never code or paths. The `supported_runtimes` table in `rubric.json` is a working
  assumption that must be verified by hand.
- **PostgreSQL, Sequelize and `pg` versions are unverified assumptions** (`supported_runtimes.unverified`, dated 2026-10-26): PostgreSQL 14–18
  are the majors that endoflife.date lists as supported on that date (14 reaches end of life on 2026-11-12), Sequelize 6 and `pg` 8 are the
  `latest` npm dist-tags on that date, and Sequelize 7 was still an alpha. PostgreSQL support is read from endoflife.date on every run with a network;
  Sequelize and `pg` have no such source and only the table applies. The PostgreSQL version of the *evaluated app* is read from the image tag of its
  `docker-compose.yml` (`postgres:16-alpine` → 16); an image without a version tag (`postgres`, `postgres:latest`) is reported and not checked.

## Relational schema (data model)

- **Static extraction is a subset parser, not PostgreSQL.** It understands `CREATE TABLE`, `ALTER TABLE` (add/drop column and constraint,
  set/drop not null and default, type), `CREATE [UNIQUE] INDEX`, `DROP TABLE/INDEX`; it ignores the `down` half of migrations (`-- migrate:down`,
  `+goose Down`, `*.down.sql`, `down()`), views, functions, triggers, partitions, `RENAME`, inheritance and `CREATE TABLE … AS`. What it cannot
  read is listed in `metrics.json` (`schema.unparsed`). Schemas other than `public` are ignored by name.
- **Sources.** SQL files, Sequelize migrations (`queryInterface.*`) and Sequelize models are read. Knex migrations, Prisma `schema.prisma`, TypeORM
  entities and `sequelize-typescript` decorators are not: such an app has no `data_schema` artifact (not evaluable) unless it also ships SQL migrations.
  Table and column names that are not string literals (variables, template strings) are skipped and reported as `unparsed`.
- **Order of the SQL.** `.sql` files are applied in path order and then the DDL strings the backend runs at start-up; the order in which the
  code actually runs them is not followed. An `ALTER TABLE` or `CREATE INDEX` on a table not created yet is therefore retried after all of
  them (an app may create its base tables in a start-up string and alter them in a `.sql` file it reads afterwards); only what still has no
  table is reported as `unparsed`.
- **Secondary databases (r2, Requirement 1).** SQL meant for the read replicas is kept out of the main schema and listed in
  `schema.secondary_sql`: SQL Server (T-SQL) syntax (`GO`, `IDENTITY(1,1)`, `NVARCHAR`, `dbo.`…) or a file path naming a replica or SQL
  Server (`replica`, `replication`, `mssql`, `sqlServer…`). It is a heuristic: a main schema kept under such a path would be skipped, and
  replica DDL with plain PostgreSQL syntax in an unremarkable path would still count (when its tables have the same names, the first
  file in path order decides them).
- **Preference per table.** A table is decided entirely by the first source that defines it (SQL, then Sequelize migrations, then Sequelize models);
  a model's `belongsTo` does not add a foreign key to a table whose migration lacks it, because in the database it would not exist. Table names are
  matched ignoring case and `_`.
- **Sequelize defaults are approximated.** Default table names use a simple English pluralizer (not the `inflection` library); default foreign key names
  follow Sequelize 6 (`UserId`, or `user_id` with `underscored`); model options are read when written in the call or held in a `const` object
  (also through a spread such as `{ ...options, tableName }`), but not when built at run time; `define` options set globally on the `Sequelize` instance (`timestamps: false`,
  `underscored: true`) are not visible to the evaluator. Model `validate` rules are application-level and not counted as constraints.
- **Query filters.** Only Sequelize `findOne/findAll/findAndCountAll/findOrCreate/count/max/min/sum/update/destroy` with a literal `where`, and the `WHERE`
  clause of raw SQL strings, are read. Filters through other helpers, `include` conditions and dynamically built `where` objects are not (the metrics report
  how many queries were unresolved or dynamic). With nothing to check, C4 reduces to the foreign key indexes.
- **Thresholds carried over, not calibrated.** `constraints_min_pct = 50` and `unindexed_queries_max_pct = 0` come from the previous (Mongo) rubric. C3 counts
  `NOT NULL`, `UNIQUE`, `CHECK` and foreign keys as constraints; a money-like column is recognized by name (`relational.money_name_pattern`) and only
  floating-point types are flagged, so `price TEXT` is not.
- **Implicit relations are recognized by name** (`*_id`, `*Id`): a join column named otherwise (`product_ref`) is not detected, and a `*_id` column that
  intentionally holds an external identifier is reported as an implicit relation. A polymorphic association is recognized only by its discriminator
  column (`<x>`, `<x>_type`, `<x>_table`, `<x>_kind`, `<x>_model`, `<x>_name`) and only when no table is named `<x>`.
- **The ER comparison is tolerant on names, strict on structure.** Entity names are compared ignoring case, `_` and plurals; attributes ignoring case and `_`.
  Differences in attribute types and in optionality (zero vs. one) are listed but do not fail C6. A many-to-many line drawn between two entities when the
  schema has a join table counts as a mismatch. Mermaid syntax beyond entities, attributes with `PK`/`FK`/`UK`, and relationship lines is ignored.
  With a live database, C6 compares the ER against the real schema, not the static one.

## Real database

- **Synthetic and few data.** The 25 users and their orders come from `pg_seed.py`, not from real traffic. They serve to compare apps
  with each other, not to predict production behavior: index usage (`pg_stat_user_indexes`) with so few rows is not representative (which is
  why it is reported but not used as a criterion).
- **It depends on an external PostgreSQL** and on the app creating its schema when it starts (`npm start`). If the app does not start, or the database has
  no tables afterwards (for example, the migrations must be run by hand with `sequelize-cli`), the static analysis is used and `profile.md` shows it
  (`live_database: false`).
- **Queries are read from the code** (Sequelize `where`, raw SQL `WHERE`): those that go through helpers with another name, that are built
  dynamically, or that belong to a model the evaluator cannot map to a table are not associated with a table and do not count (the number is in the metrics).
- **Security:** it runs code generated by a model with the credentials of `PG_ADMIN_URL`' role (the app connects with the same role; the admin URL variable itself is
  not passed on). PostgreSQL cannot restrict a role to databases by name pattern: use a role with `CREATEDB` and no superuser rights, on a disposable server,
  so that it can only drop databases it owns. The scripts themselves only create, read and drop `eval_*` databases.
- **Create/drop were not run against a real server in development.** `pg_schema.js dump` was verified against PostgreSQL 18.6 (PGlite, over the wire protocol);
  `CREATE DATABASE` / `DROP DATABASE` (PGlite has a single database) were not.

## The judge

- **It is an opinion, not a measurement.** Its decisions (`source: judge (model)`) must be cited as such and weigh more the more
  criteria it decides. Always report the "without judge" range that `profile.md` writes.
- **Model bias.** A judge from the same family as the generator may favor its own style. A different model is required: names are
  compared after removing provider prefixes and date or bracket suffixes, and a family alias (`sonnet`) counts as the same model
  as any version of it; the judge also refuses to run when the generator model was not recorded. Different models of the same family
  (Opus judging Sonnet) are allowed: choose with that criterion in mind.
- **Non-deterministic.** Two runs may differ. The 3 votes with a majority reduce this, they do not eliminate it. Keep `judge.json` with the
  results: it is what allows the decision to be reproduced without querying again.
- **It sees an excerpt.** It receives the evidence that `judge.py` builds, not the whole application: for the data model the schema files (up to
  400 lines each), the ER document and the design documents that mention snapshots or denormalization go in whole; the README, the queries and
  the routes fill the rest of a 60 000-character budget. When something is cut the prompt says so and the judge is told to answer "I don't know"
  if the decision depends on it.
- **One prompt per point.** The pending criteria of a point are asked together, with one policy for what counts as a justified copy, so that C2
  and C5 cannot decide the same column differently. Judge decisions made before this change (one prompt per criterion) are not comparable.
- **Uncalibrated.** Its agreement with human reviewers has not been measured. Until that is done, audit the sample that `judge.json` flags.

## Experiment

- **The generator model is a variable.** If the model changes, the result changes. Always record `--model`: `cli.py evaluate`, `evaluate.py run` and
  `run_experiment.py` refuse to run without it (`--allow-missing-model` overrides this and `profile.md` / `report.md` then say so), and it is recorded in
  `results/environment.json`. The
  applications in the example run were generated with subagents whose model was assumed to be the same as the session's. The pilot's
  `experimentos/*/meta.json` files have `"modelo": null`: the model was not recorded and cannot be reconstructed from this repository.
- **The specifications differ in more than one aspect** between levels (architectural style, quality attributes,
  guidelines). A difference between levels cannot be attributed to just one of those variables.
- **Tokens depend on the agent, not only on the code.** The same model with another CLI version, other system instructions, other tools or
  another effort level consumes different tokens for the same task. Compare tokens only between runs with the same agent, version and
  configuration, and record them (`agent_version` in `meta.json` with `run_experiment.py`).
- **Tokens are not cost.** `total_tokens` adds cache reads, which are billed at a fraction of a fresh input token, to everything else. Two
  agents with similar totals can have very different costs; look at `cache_read_tokens` and `output_tokens`, and at `cost_usd` when the
  source reports it (Claude `-p --output-format json`).
- **Attribution of sessions.** `token_usage.py scan` guesses the app and the phase of each session from its prompt (or, for Codex subagents,
  from the whole transcript) and must be checked before recording. Work done in a session that orchestrated several apps is not
  attributed to any of them, so the recorded figure is a lower bound of the real effort when the orchestrator did part of the work.
  The Claude Code transcripts de-duplicate messages by id; a transcript cut off by a crash or rotated by the client undercounts.
- **One run per phase.** Token consumption varies a lot between repetitions of the same prompt; with a single run per app and phase the
  R2 / initial ratio is an observation, not an estimate.
- **Two small domains.** The requirements are those of a small e-commerce and a small cinema ticket sale (≈ 750–960 production lines
  per app in the pilot). It is not known whether the results hold in larger applications or in other domains.
- **The specifications changed after the first generation.** `technical-n3.md` and `combiner-prompt.md` were made domain-neutral
  (their patterns and examples used to name only the e-commerce: cart, stock, order statuses, volume discount), and
  `r2-additional-requirements.md` gained a fixed HTTP interface for Requirements 1 to 5, the `docs/R2/` layout, the `SEED_DATE`
  variable and the replica configuration. Applications generated with the previous texts (the first 12 apps, both phases) are not
  strictly comparable with applications generated with the current ones; record which version of `specs/` each run used (its git
  commit).

## Security

Running the tests of a model-generated application runs untrusted code: dependencies and `npm install` scripts
included. Use a virtual machine or a disposable container.

## Backing of the thresholds

- **Only ISO/IEC 5055:2021 supplies numeric thresholds** among the standards of this study. ISO/IEC 25010:2023 is a quality model and
  defines no measure; ISO/IEC 25023:2016 supplies measurement functions but its Scope states that it "does not assign ranges of values
  of the measures to rated levels or to grades of compliance"; IEEE Std 1028-2008 governs the review process, not the metrics. Every
  threshold is classified by strength of backing in `rubric.json` under `backing`, and the ones typed `own_calibration` have **no
  source among these standards**. Read that map before citing any threshold as standards-based.
- **DL and PC have no normative backing.** Decoupling Level and Propagation Cost are metrics of the DV8 tool: neither is a measure of
  ISO/IEC 25023 nor a weakness of ISO/IEC 5055, so neither the metrics nor their cut-offs (60% and 20%) rest on the standards of this
  study. They are declared as additional quality measures under ISO/IEC 25023 Clause 2(e), whose specification format lives in
  ISO/IEC 25021, which is not part of this study.
- **Line and branch coverage are not a testability measure.** ISO/IEC 25023 does carry a test coverage measure, RMa-4-S, but it sits
  under Reliability/Maturity, is external, and defines coverage as the capabilities, scenarios or functions actually performed against
  those included in the test suites, not as line or branch coverage. The 70% and 50% cut-offs have no source. The genuine generic
  testability measure, MTe-1-G, is not implemented, so the subcharacteristic carrying the largest weight (30%) rests on a measure the
  standard places elsewhere.
- **Two highly recommended measures of modifiability are missing.** MMd-1-G and MMd-2-G are the only Generic measures of modifiability
  and both are classified HR in ISO/IEC 25023, Annex A. Both require actual modification events, which a freshly generated application
  does not have, so they are excluded under Clause 2(b). Section 6.2 of the standard recommends relating internal measures to the
  external measures they are meant to predict, so the profile this framework produces is not validated against them.
- **The weights come from a panel of four with low concordance.** Kendall's W over the rankings of Table 23 of PIA02 is 0.158
  (chi-square 2.52, 4 df, critical value 9.49 at alpha 0.05): not statistically significant. The ranking of E4 also sums 17 instead of
  15, because it assigns rank 5 twice and omits rank 3. Treat 30/24/24/22 as the priority profile of a small, dispersed panel. The
  report includes a sensitivity analysis (uniform 25%, equal points, each point removed, and optional per-expert sets; see
  [methodology](methodology.md#weight-sensitivity)): cite only the conclusions that hold across it.
- **The Technologies point has no backing at all.** Dependency obsolescence is not a weakness of the maintainability measure and is not
  among the analysability or modifiability measures of ISO/IEC 25023. Counting high and critical vulnerabilities inside a
  maintainability point also borrows from the Automated Source Code *Security* Measure, which the standard does not authorize.
- **Of the 25 applicable ASCMM weaknesses, 15 are scored, 7 are only informational and 3 are not detected**
  (`backing._coverage_ascmm`). Informational: CWE-480, 570, 571, 783, 1064, 1085 and 1095 (supplementary indicators, group ASCMM).
  Not detected: CWE-407, 1084 and 1090. Four of the 29 do not apply to JavaScript or TypeScript.
- **The ASCMM density is per KLOC, not per AFP.** ISO/IEC 5055 Annex C.1 divides the occurrences by Automated Function Points, which are
  not computed; KLOC of production code is a substitute that rewards verbose code (more lines, lower density). The total adds
  occurrences of different kinds (a function, a file, a cycle), as the standard does, and leaves out the 3 weaknesses not detected, so
  it is not comparable with an ASCMM measured by a certified tool such as CAST.
