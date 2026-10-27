# Presentation script for the maintainability evaluation framework

Estimated duration: 30–35 minutes (25 of talk and demo, 5–10 of questions). Each block carries: **what to say**, **what to show**
and, when useful, **what to avoid claiming**. The numbers in block 9 come from the example run and are preliminary.

Preparation before starting: terminal at the repository root, `python cli.py doctor` already run with no errors,
`results/` with the example run, and `README.md`, `rubric.json` and `results/report.md` open.

---

## 1. Opening: the problem (2 min)

**What to say**
- AI agents generate complete applications from a specification. The practical question is: *how much does the
  maintainability of the code they produce change depending on how much technical detail they are given?*
- To answer it we need a way to measure maintainability that is **repeatable**, **traceable** and **explicit about what
  it cannot decide**. That is the framework: it is not a magic number, it is a protocol with a tool.
- Three ideas guide the whole design: (1) measure with evidence from the code, not with opinion; (2) separate what is automatic from what
  requires human judgment; (3) if it cannot be decided, say so with a **range**, do not invent a value.

**What to show:** `README.md`, first screen.

---

## 2. Overview: three steps (2 min)

**What to say**
1. **Create** the applications (one per specification level), each with no context from the others.
2. **Evaluate**: a single command measures the 11 points in all of them.
3. **View results**: a report with the profile, the pending items and the warnings.
- Between step 2 and step 3 there is an optional **manual review** loop that closes the ranges.

**What to show:** the "Usage: three steps" block of the README and the "Repository contents" table.

---

## 3. The experiment: three specification levels (3 min)

**What to say**
- The functional requirements are the same for everyone: a small e-commerce (catalog, cart, registration and login,
  checkout, orders, volume discount).
- What varies is the technical specification, from less to more guidance:
  - **N1**: only the MERN stack and a layered monolith.
  - **N2**: N1 plus expected quality attributes (understandable, modifiable, testable).
  - **N3**: N2 plus explicit architectural guidelines (single responsibility, dependency injection, unit
    tests, validation, documenting decisions).
- A single prompt combines the technical specification and the requirements. Each app is generated in an empty folder, with only its two
  documents and in a new session: **isolation** so that one level does not contaminate another.

**What to show:** `specs/` and `docs/generating-apps.md`.

**What to avoid claiming:** that the difference between levels is due to a single variable. Each level changes several things at once.

---

## 4. The evaluation model: 11 points, 4 subcharacteristics (4 min)

**What to say**
- **11 decision points** are evaluated, grouped into three categories: *structure and modularity* (layers, cyclomatic
  complexity, cohesion, hierarchies), *dependencies and integration* (technologies, coupling, data model, contracts) and
  *cross-cutting quality* (observability, tests, configuration).
- Each point has criteria C1, C2… that are either met or not. A **level** comes out of that: Meets if all are met, Partial if at
  least half, Fails if fewer. Two criteria are mandatory and force "Fails" if they fail: that a machine-readable
  contract exists and that tests exist and pass.
- The points feed **four subcharacteristics**: Testability 30%, Analyzability 24%, Modularity 24% and
  Modifiability 22%. Each level is worth 1, 0.5 or 0; the subcharacteristic is the average of its points and the overall score is the weighted
  sum, from 0 to 100.
- Each point is automatic, mixed or manual. Not everything is automatable and the framework acknowledges it.

**What to show:** `docs/methodology.md`, the table of the 11 points; and `rubric.json` (weights and thresholds).

**Key message:** *every threshold lives in `rubric.json`*. Changing the rubric does not require touching the code.

---

## 5. Ranges: how uncertainty is handled (3 min)

**What to say**
- A criterion the program cannot decide stays **pending**. The framework evaluates it twice, as met and as not
  met, and reports the score as **minimum–maximum**.
- A wide range is not a failure: it is honest information about how much is left to review. When a person resolves the
  pending items, the range closes to a number.
- It is the most important design decision: we prefer "between 37 and 56" to a "47" that looks precise but hides assumptions.

**What to show:** the report, "Overall result" table, and the note on ranges.

---

## 6. The tool: architecture and walkthrough (5 min)

**What to say** (go through in this order, one sentence per piece)
- **`cli.py`**: single entry point with three commands: `doctor` (is the environment ready?), `evaluate` and `report`.
- **`evaluate.py`**: the core. Collects evidence, evaluates the 11 points, builds the profile and aggregates several apps.
- **`ast_metrics.js`**: static code analysis with `ts-morph`. Extracts functions and cyclomatic complexity, fan-out,
  classes and inheritance, literals, `catch` blocks, `console` calls, Express routes and Mongoose schemas.
- **External tools**:
  - `dependency-cruiser`: dependency graph between modules and cycles.
  - `depcheck`: dependencies declared but unused.
  - the **npm** registry: versions, deprecated packages and `npm audit` for vulnerabilities.
  - **Spectral**: quality of the OpenAPI contract, if there is one.
  - the project's own **test runner**, with coverage.
  - **DV8**: Decoupling Level and Propagation Cost.
- **`dv8_metrics.py`** and **`manual_template.py`**: bridges we will see next.
- **`tests/`**: 29 tests of the evaluator itself, so that whoever modifies the rubric can check they did not break anything.

**What to show:** `python cli.py doctor` live (each line explains itself) and the folder tree.

---

## 7. Where each number comes from: evidence per point (5 min)

Go through only the points the audience may question; the rest is in `docs/methodology.md`.

- **Layers**: each file's layer is deduced from the name of its directories (`controllers`, `services`, `models`…). Only
  presentation→business and business→data are allowed. It measures the percentage of inter-layer dependencies that break that rule.
- **Cyclomatic complexity**: proportion of functions with complexity greater than 20.
- **Cohesion**: high fan-out, "god" modules, and DV8's DL; the mixed-responsibilities part is human judgment.
- **Coupling**: cycles, the MMo-1-G metric, DV8's Propagation Cost and unused dependencies.
- **Technologies**: outdated versions, deprecations and vulnerabilities, queried from npm at evaluation time.
- **Tests**: existence, passing, and line and branch coverage. **The app's code is executed**.
- **Configuration**: hardcoded network literals and duplicated literals.

**What to say about DV8** (it tends to generate questions)
- DL (Decoupling Level, Mo et al.) measures how well the system decomposes into independent modules; PC (Propagation Cost,
  MacCormack et al.) measures how much a change propagates through the dependencies.
- DV8 **does not analyze JavaScript or TypeScript**. We build the dependency matrix from the `dependency-cruiser` graph
  using a template (`dv8/matrix-template.json`), convert it to DV8's native format and ask it for the two metrics.
- It is an **approximation** and that must be said: the values may differ from a native analysis.

**What to show:** `results/<app>/dv8/` (matrix, `dl.json`, `pc.json`) and `docs/methodology.md`.

---

## 8. Methodological decisions and why (5 min)

This block tells the decisions we made when testing the framework with real data. It is what most convinces the audience that
the design is well thought out.

1. **Test runner.** The evaluator assumed Jest; the apps used Node's native runner and all came out as "tests
   failed" because of an instrument failure. Now it detects `node --test` and reads coverage in lcov format.
   *Lesson: an instrument that assumes one tool biases against whoever uses another.*
2. **Duplicated literals.** At first they were compared with the median of the evaluated apps: one app's result changed when
   another was added. We replaced it with **SonarQube rule S1192** (threshold of 3 repetitions, minimum length 10, no
   single words), verified in the `eslint-plugin-sonarjs` plugin's code. It is **absolute** and reproducible.
3. **Layers with ambiguous evidence.** With dependency injection no layer imports another and the criterion came out "Meets" with no
   evidence. Now, zero inter-layer dependencies, or a violation that depends on an ambiguous directory such as `domain`, leaves
   the criterion **pending** manual review instead of deciding by the heuristic.
4. **DL without isolated files.** DV8 reports 100% DL if there is an isolated file (for example `vite.config.js`), which
   distorts it. We use the value without isolated files and record both.
5. **Unhealthy Inheritance.** Requires the project's own base class. If all classes inherit from `Error`, the count
   is 0; if there is an own hierarchy, it is reviewed by hand with DV8's criteria.

**Key message:** each decision replaces a misleading result with an explicit one or with a pending item.

---

## 9. Live demo and reading the results (5 min)

**Sequence**
1. `python cli.py evaluate --model "<model>"` (or show the output already generated, because it takes a few minutes).
2. Open `results/report.md` and go through it top to bottom: overall result, points matrix, pending manual
   review, findings, warnings and environment.
3. Open a `manual_review.md` and show what the evidence for deciding a criterion looks like.

**How to read the numbers of the example run** (N1, N2 and N3; one run per level)
- Overall: N1 **40.2–56.1**, N2 and N3 **36.8–56.1**. The ceilings coincide and the floors depend on pending decisions
  about Layers, not on a real difference in quality.
- Tests: 2, 6 and 23 cases; N3 is the only one close to the line coverage threshold in the backend (53% versus 70%).
- Constant across the three levels: no OpenAPI contract, no logger, and the same 10 dependencies with outdated
  versions. Those gaps **do not depend on the specification level**.

**What to avoid claiming:** that one level "wins". With one run per level and open ranges, the comparison is **preliminary**.

---

## 10. Limitations, stated by us (3 min)

Stating them before they are asked conveys rigor. Summary of `docs/limitations.md`:
- MERN applications only, with `backend/` and `frontend/`.
- It is not verified that the apps work (without MongoDB there is no acceptance gate).
- One run per combination: no statistical basis.
- Layers by directory name; DL and PC on a derived matrix; branch coverage overestimated with the native runner.
- The **generator model is a variable**: it must be recorded.
- Small domain and scale (fewer than 1,000 production lines per app).
- **Security**: evaluating with tests runs model-generated code; use a virtual machine or container.

---

## 11. Closing (1 min)

**What to say**
- What it contributes: a repeatable protocol with a tool, which says clearly what it measures, what it cannot decide and what assumptions it
  uses.
- What comes next: complete the manual review to close the ranges, repeat each level several times, add the acceptance
  gate and try other domains and other models.
- Invitation: the repository is meant for other people to use with their own applications and adjust
  `rubric.json`.

---

## Questions they will probably ask (and short answers)

- **Why those 11 points and those weights?** They come from the framework's design (PIA-02, rubric tables); I did not recompute them
  here. They are in `rubric.json` and can be adjusted.
- **Why not report a single number?** Because there would be undecided criteria. The range says how much is missing.
- **Why DV8 if it does not support JavaScript?** Because DL and PC are established architecture metrics; we use their computation on
  a derived matrix and declare the approximation.
- **How reliable is the layer heuristic?** It is a heuristic. That is why, when the evidence is ambiguous, human
  review is requested, and a classification can be imposed with `.layers.json`.
- **Can it be used with another stack?** The evaluator assumes MERN; adapting it requires changing `ast_metrics.js` and the package
  detection.
- **What happens if the rubric changes?** Edit `rubric.json` and run the tests with
  `python -m unittest discover -s tests -v`.
- **Are the results reproducible?** They are for the static analysis. npm queries change over time, and that is why
  each run records the date and versions in `environment.json`.
