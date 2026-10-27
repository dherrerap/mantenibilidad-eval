# Limitations

What the framework does **not** guarantee. Cite them alongside any result.

## Scope

- **MERN applications only** with `backend/` and `frontend/` folders, each with its own `package.json`. Other structures require
  adjusting `ast_metrics.js` and the package detection.
- **It does not evaluate whether the application works.** Without the acceptance gate (`acceptance_check.py` against MongoDB) a high
  score may correspond to a broken app. It is a maintainability measure, not a correctness one.
- **A single run per combination.** With one run per level there is no statistical basis to claim that one level beats
  another. Differences of a few points are within the margin left by the pending criteria.
- **The result is a range** as long as there are pending criteria. The ends are bounds, not estimates.

## Measurement

- **Layers by directory name.** It is a heuristic. An app that organizes its layers with other names, or that connects them
  through dependency injection, gets "pending" and not an automatic result. Ambiguous directories (`domain`, `core`,
  `entities`) also leave the criterion under review.
- **DL and PC on a derived matrix.** DV8 does not analyze JavaScript or TypeScript. The matrix comes from the `dependency-cruiser`
  graph, with a single dependency type (`Import`), and the values may differ from those of a native analysis.
  With projects of fewer than 100 files they are sensitive to each dependency.
- **Unhealthy Inheritance** is decided with DV8's two rules applied by the framework to the import graph and the project's own classes
  (a parent that imports its child, or a client that imports both), not with DV8's detection: `arch-issue` needs inheritance
  edges and, for other detectors, git history, which the evaluated applications do not have. The **cliques** are also
  computed on the graph (strongly connected components), not with DV8.
- **Coverage with `node --test`** is measured with `c8 --all`. If `c8` is not installed, Node's native coverage is used, which
  overestimates branches because the files that no test loads do not enter the denominator.
- **Duplication (jscpd)** is informational and detects textual clones by tokens; it does not see semantic duplication. The 5% threshold
  is an external practice, not our own study.
- **Cognitive complexity and dead code** are our own approximations, not the output of SonarQube or `knip`. Dead
  code only sees files without importers; it does not detect unused exports or functions. Both are informational.
- **Data model C2/C5 suggestions and contracts C4** are heuristics over the code text (declared types, `populate`,
  validation middleware names). They do not compare the schema with the contract field by field.
- **Supplementary indicators** are heuristics over the code text and are not scored. "Without assertions" only recognizes
  `assert`, `expect` and `should`; credential detection looks at the variable name; the NoSQL check only sees
  `req.body/query/params` passed directly to the query; the prop count of a component that receives `props` without
  destructuring is approximate. There is no mutation testing, dependency licenses or unused exports.
- **Observability C1** is a proxy: critical events are `catch` blocks, functions that use `bcrypt`/`jwt`/`passport`
  (authentication) and those that write with Mongoose (`save`, `create`, `update*`, `delete*`). A function counts as logged if it
  calls a logger or if the app has a request logger (`morgan`, `pino-http`…). It does not tell whether the message is useful.
- **Data model heuristics.** For example, a subdocument embedded in another schema may not be detected as an explicit
  relation. That is why the suggestions do not count unless accepted.
- **Technologies** depends on the moment of the query: npm versions, deprecations and vulnerabilities change over
  time. The run records the date in `environment.json`. The `supported_runtimes` table in `rubric.json` is a working
  assumption that must be verified by hand.
- **Duplication threshold (S1192).** It comes from a widely used external practice, not from our own calibration study.

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
- **Model bias.** A judge from the same family as the generator may favor its own style. A different model is required, but
  the family is not controlled: choose with that criterion in mind.
- **Non-deterministic.** Two runs may differ. The 3 votes with a majority reduce this, they do not eliminate it. Keep `judge.json` with the
  results: it is what allows the decision to be reproduced without querying again.
- **It sees an excerpt.** It receives the evidence that `judge.py` builds (first lines of the relevant files), not the whole application.
- **Uncalibrated.** Its agreement with human reviewers has not been measured. Until that is done, audit the sample that `judge.json` flags.

## Experiment

- **The generator model is a variable.** If the model changes, the result changes. Always record `--model`. The
  applications in the example run were generated with subagents whose model was assumed to be the same as the session's.
- **The specifications differ in more than one aspect** between levels (architectural style, quality attributes,
  guidelines). A difference between levels cannot be attributed to just one of those variables.
- **Single domain.** The requirements are those of a small e-commerce (≈ 750–960 production lines per app). It is not known whether
  the results hold in larger applications or in another domain.

## Security

Running the tests of a model-generated application runs untrusted code: dependencies and `npm install` scripts
included. Use a virtual machine or a disposable container.
