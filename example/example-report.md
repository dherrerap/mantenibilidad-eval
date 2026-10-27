# Maintainability report

Generated: 2026-10-14 00:05 · 3 application(s)

## Overall result (0–100)

| Application | Level | Overall | Testability | Analyzability | Modularity | Modifiability | Complete |
|---|---|---|---|---|---|---|---|
| claude-n1-ecommerce-r1 | N1 | **40.2–56.1** | 25.0 | 33.3–66.7 | 57.1–78.6 | 50.0–62.5 | no |
| claude-n2-ecommerce-r1 | N2 | **36.8–56.1** | 25.0 | 33.3–66.7 | 42.9–78.6 | 50.0–62.5 | no |
| claude-n3-ecommerce-r1 | N3 | **36.8–56.1** | 25.0 | 33.3–66.7 | 42.9–78.6 | 50.0–62.5 | no |

A range (a–b) indicates pending criteria: the real value lies between both ends until the manual review is completed.

## Decision points

✔ Meets · ◐ Partial · ✘ Fails · a…b range due to pending criteria · ? not evaluated

| Point | claude-n1-ecommerce-r1 | claude-n2-ecommerce-r1 | claude-n3-ecommerce-r1 |
|---|---|---|---|
| Separation of responsibilities between layers | ✔ | ✘…✔ | ✘…✔ |
| Cyclomatic complexity | ✔ | ✔ | ✔ |
| Cohesion of modules with shared responsibility | ✘…◐ | ✘…◐ | ✘…◐ |
| Depth and breadth of inheritance or composition hierarchies | ✔ | ✔ | ✔ |
| Technology/framework selection and obsolescence risk | ◐ | ◐ | ◐ |
| External coupling and volume of declared dependencies | ✔ | ✔ | ✔ |
| Data model design | ✘…✔ | ✘…✔ | ✘…✔ |
| Definition of communication contracts between components | ✘ | ✘ | ✘ |
| Presence and consistency of observability mechanisms | ◐ | ◐ | ◐ |
| Test coverage and design | ◐ | ◐ | ◐ |
| Separation of configuration and code | ◐ | ◐ | ◐ |

## Pending manual review

- **claude-n1-ecommerce-r1** — cohesion: C3; data_model: C1, C2, C3, C4, C5; contracts: C4 → `claude-n1-ecommerce-r1/manual_review.md`
- **claude-n2-ecommerce-r1** — layers: C2; cohesion: C3; data_model: C1, C2, C3, C4, C5; contracts: C4 → `claude-n2-ecommerce-r1/manual_review.md`
- **claude-n3-ecommerce-r1** — layers: C2; cohesion: C3; data_model: C1, C2, C3, C4, C5; contracts: C4 → `claude-n3-ecommerce-r1/manual_review.md`

## Findings per application

### claude-n1-ecommerce-r1
- **Cohesion of modules with shared responsibility** (✘…◐): 5 of 121 functions with fan-out > 5; 0 candidate 'god' module(s).
- **Technology/framework selection and obsolescence risk** (◐): 10 direct dependencies: 0 deprecated, 8 with an outdated major, 1 high/critical vulnerabilities.
- **Data model design** (✘…✔): 4 Mongoose schemas detected.
- **Definition of communication contracts between components** (✘): No machine-readable contract; 7 implemented routes.
- **Presence and consistency of observability mechanisms** (◐): 4 catch blocks (0 log, 4 delegate, 0 silent); 4 console.*; 1 error middleware(s).
- **Test coverage and design** (◐): 2 test cases; line coverage 5%, branches 100%.
- **Separation of configuration and code** (◐): 7 network literals; 0 duplicated literal(s) per S1192 (35.8 repetitions/KLOC, informational).

### claude-n2-ecommerce-r1
- **Separation of responsibilities between layers** (✘…✔): Layers detected: data, business, presentation; 1 of 13 dependencies break the rule, 1 because of a doubtful classification (ambiguous directory): from Fails to Meets depending on manual review (layers.C2) or a .layers.json.
- **Cohesion of modules with shared responsibility** (✘…◐): 5 of 145 functions with fan-out > 5; 0 candidate 'god' module(s).
- **Technology/framework selection and obsolescence risk** (◐): 10 direct dependencies: 0 deprecated, 8 with an outdated major, 1 high/critical vulnerabilities.
- **Data model design** (✘…✔): 4 Mongoose schemas detected.
- **Definition of communication contracts between components** (✘): No machine-readable contract; 7 implemented routes.
- **Presence and consistency of observability mechanisms** (◐): 4 catch blocks (0 log, 4 delegate, 0 silent); 3 console.*; 1 error middleware(s).
- **Test coverage and design** (◐): 6 test cases; line coverage 11%, branches 92%.
- **Separation of configuration and code** (◐): 7 network literals; 0 duplicated literal(s) per S1192 (33.6 repetitions/KLOC, informational).

### claude-n3-ecommerce-r1
- **Separation of responsibilities between layers** (✘…✔): Layers detected: data, business, presentation; 0 inter-layer dependencies (possible dependency injection): no structural evidence; requires manual review (layers.C2).
- **Cohesion of modules with shared responsibility** (✘…◐): 6 of 183 functions with fan-out > 5; 0 candidate 'god' module(s).
- **Technology/framework selection and obsolescence risk** (◐): 10 direct dependencies: 0 deprecated, 8 with an outdated major, 1 high/critical vulnerabilities.
- **Data model design** (✘…✔): 4 Mongoose schemas detected.
- **Definition of communication contracts between components** (✘): No machine-readable contract; 7 implemented routes.
- **Presence and consistency of observability mechanisms** (◐): 4 catch blocks (0 log, 3 delegate, 1 silent); 4 console.*; 1 error middleware(s).
- **Test coverage and design** (◐): 23 test cases; line coverage 31%, branches 94%.
- **Separation of configuration and code** (◐): 7 network literals; 0 duplicated literal(s) per S1192 (26.0 repetitions/KLOC, informational).

## Methodological warnings

- Each level has a single run: differences between levels are not statistically conclusive.
- The applications are not run against MongoDB (no acceptance gate): it is not known whether they work.
- Layer classification is a directory-name heuristic; review `detected_layers.json`.
- Test coverage: with `node --test`, files that no test loads count as 0%, but their branches do not enter the denominator (branches overestimated).
- DV8's DL and PC are computed on a matrix derived from dependency-cruiser (DV8 does not analyze JS/TS) and without isolated files.

## Environment

Python 3.12.10 · Node v22.17.1 · npm 10.5.0 · DV8: C:\Program Files\DV8\bin\dv8-console.exe
System: Windows-11-10.0.26300-SP0 · evaluated on 2026-10-13T23:58:57 · supported-runtimes table dated 2026-10-14
