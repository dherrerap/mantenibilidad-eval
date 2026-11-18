# Presentation script for the maintainability evaluation framework

Estimated duration: 35–40 minutes (30 of talk and demo, 5–10 of questions). Each block carries: **what to say**, **what to show**
and, when useful, **what to avoid claiming**. Block 10 has no numbers on purpose: fill them in from the first PERN run of the
experiment (`results/report.md`); the only report kept in `example/` belongs to the earlier MERN version and must not be shown as a
result.

Preparation before starting: terminal at the repository root, `node js/cli.mjs doctor` already run with no errors (Node.js 22 LTS,
`npm install` done), `results/` with an evaluated run, and `README.md`, `rubric.json`, `results/report.md` and one
`results/<run>/profile.md` open.

---

## 1. Opening: the problem (2 min)

**What to say**
- AI agents generate complete applications from a specification. The practical question is: *how much does the
  maintainability of the code they produce change depending on how much technical detail they are given?* And a second one: *does a
  more maintainable application cost the agent less to modify later?*
- To answer them we need a way to measure maintainability that is **repeatable**, **traceable** and **explicit about what
  it cannot decide**. That is the framework: it is not a magic number, it is a protocol with a tool.
- Three ideas guide the whole design: (1) measure with evidence from the code, with maintained tools wherever one exists, not with
  opinion; (2) separate what is automatic from what requires human judgment; (3) if it cannot be decided, say so with a **range**, do
  not invent a value.

**What to show:** `README.md`, first screen.

---

## 2. Overview: three steps (2 min)

**What to say**
1. **Create** the applications (one per agent, domain and specification level), each with no context from the others, in two
   phases: *initial* (build it) and *r2* (implement additional requirements on top of it). The tokens of each phase are recorded.
2. **Evaluate**: a single command measures the 11 points in all of them.
3. **View results**: a report with the profile, its sensitivity to the weights, the ISO/IEC 5055 weaknesses, the tokens, the pending
   items and the warnings.
- Between step 2 and step 3 there is an optional **manual review** loop that closes the ranges, and an optional **judge** (another
  model) for the design-judgment criteria.

**What to show:** the "Usage: three steps" block of the README and the "Repository contents" table.

---

## 3. The experiment: levels, domains and phases (3 min)

**What to say**
- Two small domains with the same requirements for every level: an **e-commerce** (catalog, cart, registration and login, checkout,
  orders, volume discount) and a **cinema** ticket sale (screenings, seat map, seat locks, dynamic price).
- What varies is the technical specification, from less to more guidance:
  - **N1**: only the **PERN** stack (PostgreSQL, Express, React, Node), a layered monolith and the delivery conditions.
  - **N2**: N1 plus expected quality attributes (understandable, modifiable, testable).
  - **N3**: N2 plus explicit architectural guidelines (single responsibility, dependency injection, unit tests, validation,
    documenting decisions).
- One prompt combines the technical specification and the requirements, with cross-cutting deliverables for every level: code
  comments, the entity-relationship model (`docs/entity-relationship-model.md`) and the **OpenAPI contract** (`docs/openapi.yaml`).
- Phase **r2** adds nine requirements (replicas, auditing, roles…) in a **new session**, and the documentation is delivered again in
  `docs/R2/`. The tokens of both phases are the effort indicator: does the r2/initial ratio fall as maintainability rises?
- **Isolation**: each app in an empty folder, with only its documents and in a new session, so that one level does not contaminate
  another.

**What to show:** `specs/` and `docs/generating-apps.md`.

**What to avoid claiming:** that the difference between levels is due to a single variable. Each level changes several things at once.

---

## 4. The evaluation model: 11 points, 4 subcharacteristics (4 min)

**What to say**
- **11 decision points**, grouped into three categories: *structure and modularity* (layers, cyclomatic complexity, cohesion,
  hierarchies), *dependencies and integration* (technologies, coupling, data model, contracts) and *cross-cutting quality*
  (observability, tests, configuration).
- Each point has criteria C1, C2… that are either met or not. A **level** comes out of that: Meets if all are met, Partial if at
  least half, Fails if fewer. Two criteria are mandatory and force "Fails": a machine-readable contract exists, and tests exist and
  pass. The severity follows IEEE Std 1028 (Negligible, Marginal, Critical).
- The points feed **four subcharacteristics** of ISO/IEC 25010: Testability 30%, Analyzability 24%, Modularity 24% and Modifiability
  22%. Each level is worth 1, 0.5 or 0; the subcharacteristic is the average of its points and the overall score is the weighted sum,
  from 0 to 100.
- Every threshold and weight lives in `rubric.json`, and its `backing` map says where each one comes from: an ISO/IEC 5055 default, an
  ISO/IEC 25023 measurement function, a tool's rule or our own calibration.

**What to show:** `docs/methodology.md`, the table of the 11 points; and in `rubric.json` the weights, one threshold and its
`backing` entry.

**Key message:** *changing the rubric does not require touching the code, and every number declares its source.*

---

## 5. Ranges and weights: how uncertainty is handled (3 min)

**What to say**
- A criterion the program cannot decide stays **pending**. The framework evaluates it twice, as met and as not met, and reports the
  score as **minimum–maximum**. When a person (or the judge) resolves it, the range closes.
- The weights come from a panel of four experts whose agreement is **not significant** (Kendall's W = 0.158). So the report includes
  a **sensitivity analysis**: every run is scored again with uniform weights, with every point weighing the same and with each point
  removed, and it says whether the best run and the order of the levels and agents hold.
- We prefer "between 37 and 56, and the order holds under every weighting" to a "47" that looks precise but hides assumptions.

**What to show:** the report, "Overall result" table and the "Weight sensitivity" section.

---

## 6. The tool: architecture and walkthrough (5 min)

**What to say** (go through in this order, one sentence per piece)
- **`js/cli.mjs`**: single entry point with three commands: `doctor` (is the environment ready?), `evaluate` and `report`.
- **`js/evaluate.mjs` and the `evaluator/` package**: one module per source of evidence (`collectors/`), one per decision point
  (`points/`), and the scoring, dashboard and outputs. Evidence is collected once and saved in `metrics.json`; everything later (DV8,
  the live database, the judge, a manual review) only **re-scores** it.
- **`js/tools/ast_metrics.js`**: static analysis with `ts-morph`: functions and McCabe complexity, fan-out, classes and inheritance, literals,
  `catch` blocks, `console` calls, Express routes, Sequelize models and migrations, raw SQL and query filters.
- **Maintained tools, each one where it is the reference**:
  - `dependency-cruiser`: module graph and cycles.
  - **ESLint + eslint-plugin-sonarjs**: SonarQube's own rules for duplicated literals (S1192) and cognitive complexity (S3776), and the
    ISO/IEC 5055 weaknesses no point scores.
  - **Knip**: files no entry point reaches (dead code) and unused dependencies, **without executing the app**: its configuration files
    are read as source and a guard blocks any attempt to run one.
  - `jscpd`: code clones. **Spectral**: quality of the OpenAPI contract.
  - The npm registry and **OSV**: the versions the app really installs, their age in libyears and their vulnerabilities, **as of a
    fixed reference date** (`--as-of`).
  - The app's own **test runner** with `c8` coverage, and optionally **StrykerJS** (mutation score).
  - **DV8**: Decoupling Level and Propagation Cost.
- **Optional, against a running app**: the acceptance gate (`js/acceptance_check.mjs`) with PostgreSQL, the analysis of the real database
  (`--postgres`) and **Prism**, which checks every response of the gate against the OpenAPI contract.
- **`tests/`**: the evaluator's own test suite, so that whoever modifies the rubric can check they did not break anything.

**What to show:** `node js/cli.mjs doctor` live (each line explains itself) and the folder tree.

---

## 7. Where each number comes from: evidence per point (5 min)

Go through only the points the audience may question; the rest is in `docs/methodology.md`.

- **Layers**: each file's layer is deduced from its directories (`controllers`, `services`, `repositories`…). Only
  presentation→business and business→data are allowed; it measures the percentage of inter-layer dependencies that break that rule.
- **Cyclomatic complexity**: share of functions with complexity above 20 (the ISO/IEC 5055 default for CWE-1121), and duplicated code
  above 10% (CWE-1041).
- **Cohesion**: fan-out above 5 (CWE-1048), files over 1000 lines (CWE-1080), "god" modules and DV8's DL; mixed responsibilities are
  human judgment.
- **Coupling**: cycles, the MMo-1-G measure of ISO/IEC 25023, DV8's Propagation Cost, unused dependencies and dead files (Knip).
- **Data model**: primary and foreign keys, constraints, indexes on foreign keys and on the fields the code filters by, and whether the
  ER document matches the schema; on the real database with `--postgres`.
- **Contracts**: the OpenAPI exists, is valid, covers the routes and matches the validation; with the gate, whether the real responses
  match it.
- **Technologies**: deprecated packages, unsupported runtimes, outdated majors and vulnerabilities, on the resolved versions and as of
  the reference date.
- **Tests**: existence, passing, and line and branch coverage. **The app's code is executed.**
- **Configuration**: hardcoded network literals and duplicated literals (S1192).
- Next to the levels, every run reports the **occurrences of the 22 ISO/IEC 5055 weaknesses** it detects with their **density per KLOC**:
  apps generated from N1 and N3 differ in size, so densities, not counts, are compared.

**What to say about DV8** (it tends to generate questions)
- DL (Mo et al.) measures how well the system decomposes into independent modules; PC (MacCormack et al.) measures how much a change
  propagates through the dependencies.
- DV8 **does not analyze JavaScript or TypeScript**. We build the dependency matrix from the `dependency-cruiser` graph and ask it for
  the two metrics. It is a derived matrix and that must be said.

**What to show:** a `profile.md` (risk map, ISO/IEC 5055 table) and `results/<app>/dv8/`.

---

## 8. Methodological decisions and why (5 min)

This block tells the decisions made when testing the framework with real data. It is what most convinces the audience that the
design is well thought out.

1. **The test runner.** The evaluator assumed Jest; the apps used Node's native runner and all came out as "tests failed" because of
   an instrument failure. Now it detects `node --test` and measures it with `c8 --all`. *Lesson: an instrument that assumes one tool
   biases against whoever uses another.*
2. **Reference rules instead of our own.** Duplicated literals were first compared with the median of the evaluated apps, so one app's
   result changed when another was added; then with a re-implementation of S1192 that counted across the whole app. Now SonarQube's
   own rule runs, per file, as SonarQube does. The same for cognitive complexity.
3. **Layers with ambiguous evidence.** With dependency injection no layer imports another and the criterion came out "Meets" with no
   evidence. Now zero inter-layer dependencies, or a violation that depends on an ambiguous directory such as `domain`, leaves it
   **pending**.
4. **Dead code by reachability.** Counting files nobody imports missed two dead files that import each other. Knip follows the
   entry points instead, and does it without running a single line of the generated app.
5. **Reproducibility over time.** `npm audit` and "latest version" answer for today: evaluating the same app six months later gave
   another result. Now versions and advisories are fixed at a reference date (`--as-of`).
6. **A requirement nobody asked for.** The contract was mandatory but no specification asked for it, so a whole point failed for
   something the agent was never told. Now the OpenAPI is a deliverable of the prompt.
7. **DL without isolated files.** DV8 reports 100% DL when there is an isolated file (for example `vite.config.js`). We use the value
   without isolated files and record both.

**Key message:** each decision replaces a misleading result with an explicit one or with a pending item.

---

## 9. Behaviour, not only structure (2 min)

**What to say**
- Coverage says which lines the tests run; **mutation testing** (StrykerJS, `--mutation`) says whether the tests would notice if those
  lines were wrong.
- The static contract criteria say whether the document matches the routes; **Prism** says whether the running API returns what the
  contract promises.
- Both are **informational**: there is no published cut-off, and they would have to be calibrated on the experiment before scoring.

**What to show:** the Tests and Contracts rows of a `profile.md` of a run evaluated with `--mutation` and `--postgres`.

---

## 10. Live demo and reading the results (5 min)

**Sequence**
1. `node js/cli.mjs evaluate --model "<model>" --as-of <generation date>` (or show the output already generated: it takes a few minutes per app).
2. Open `results/report.md` and go through it top to bottom: overall result, weight sensitivity, ISO/IEC 5055 weaknesses, tokens, risk
   dashboard, points matrix, pending review, findings, warnings and environment.
3. Open a `manual_review.md` and show what the evidence for deciding a criterion looks like.

**How to read the numbers** (fill in from the run you show)
- The overall range of each level, and whether the floors differ because of real findings or because of pending criteria.
- Whether the order of the levels holds in the sensitivity analysis.
- The ISO/IEC 5055 density per level, not the counts.
- Tokens initial, r2 and r2/initial per app, next to the score.

**What to avoid claiming:** that one level "wins". With one run per combination and open ranges, any comparison is **preliminary**.

---

## 11. Limitations, stated by us (3 min)

Stating them before they are asked conveys rigor. Summary of `docs/limitations.md`:
- PERN applications only, with `backend/` and `frontend/`; the schema is read from SQL, Sequelize migrations or models.
- Without the acceptance gate (Docker or `--postgres`) it is not known whether the apps work.
- One run per combination: no statistical basis.
- Layers by directory name; DL and PC on a derived matrix; the rule-to-CWE mapping of the ESLint indicators is ours.
- The weights have a non-significant agreement: cite only what holds in the sensitivity analysis.
- Only ISO/IEC 5055 supplies numeric thresholds: read `backing` before calling a threshold standards-based.
- The **generator model is a variable**: it must be recorded; and tokens depend on the agent and its version, not only on the code.
- Two small domains (under 1,000 production lines per app).
- **Security**: evaluating with tests runs model-generated code; use a virtual machine or container.

---

## 12. Closing (1 min)

**What to say**
- What it contributes: a repeatable protocol with a tool, which says clearly what it measures, with which tool, from which source, what
  it cannot decide and what assumptions it uses.
- What comes next: generate every app with the current prompt, complete the manual review, repeat each combination several times,
  calibrate the informational measures (mutation score, runtime conformance) and relate the profile to the r2 effort.
- Invitation: the repository is meant for other people to use with their own applications and adjust `rubric.json`.

---

## Questions they will probably ask (and short answers)

- **Why those 11 points and those weights?** They come from the framework's design (PIA-02, rubric tables) and a Borda count over an
  expert panel. The panel's agreement is low, which is why the report shows the sensitivity analysis.
- **Why not report a single number?** Because there would be undecided criteria. The range says how much is missing.
- **Why DV8 if it does not support JavaScript?** Because DL and PC are established architecture metrics; we compute them on a derived
  matrix and declare it.
- **Is it safe to analyze code written by a model?** Static analysis yes; Knip and Prism are run so that no file of the app is
  executed. Running its tests or mutation testing executes it: do that in a disposable machine.
- **How reliable is the layer heuristic?** It is a heuristic. When the evidence is ambiguous, human review is requested, and a
  classification can be imposed with `.layers.json`.
- **Can it be used with another stack?** It assumes PERN; adapting it requires changing `js/tools/ast_metrics.js`, the schema extraction and the
  package detection.
- **What happens if the rubric changes?** Edit `rubric.json` and run the tests with `npm run test:js`.
- **Are the results reproducible?** The static analysis is. What depends on time (versions, advisories, supported runtimes) is fixed
  with `--as-of`; the deprecation of a version and the current severity of an advisory are the exceptions, documented in the limitations.
