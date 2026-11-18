# Manual review

Some criteria cannot be decided by a program. They stay **pending** and the score is a range until a person
resolves them. This page explains how to do it and how the sources are combined.

## What is reviewed

| Point | Criterion | What is decided |
|---|---|---|
| Layers | C2 | Only if there are no inter-layer dependencies, or if a violation depends on an ambiguous directory. `true`: the separation is real (or the doubtful dependency is legitimate in that architecture). `false`: there is improper coupling. |
| Cohesion | C3 | There is no "god" module, no mixing of distinct responsibilities in one module and no excessive fragmentation. |
| Data model | C2, C5 (and C1, C3, C4, C6 if the evidence misled the program) | C2 normalization (≤ 3NF) consistent with access, denormalization justified · C5 no unjustified redundancy or inconsistent types. The measured criteria: C1 primary keys and declared foreign keys · C3 constraints declared · C4 indexes on foreign keys and query filters · C6 the ER model matches the schema. |
| Contracts | C4 | Input validation is consistent with the contract. |
| Hierarchies | C3 | Only if the project defines its own base class and the dependency graph is missing, so DV8's rules could not be applied (Unhealthy Inheritance). |
| Any other point | the pending one | A criterion left pending because a measurement did not run: DV8 (cohesion C2, coupling C3), ESLint (configuration C2), Knip (coupling C4, C5), jscpd (cyclomatic C3), the tests (tests C2–C4), the network (technologies), or a reference date earlier than the app (technologies C3). `manual_review.md` lists them with the reason; the best fix is to provide what is missing and evaluate again. |

## Procedure

1. Run `node js/cli.mjs evaluate`. For each app the following are created in `results/<app>/`:
   - `manual_review.md`: statement, evidence (tables, functions with high fan-out, model code) and a suggestion
     per criterion.
   - `manual_review.draft.json`: the same structure with `ok: null`.
2. Review the evidence. The suggestions **guide, they do not decide**; they may be wrong (for example, a relation the static analysis
   could not see because the foreign key is created in a raw SQL string built at run time).
3. Copy the draft to `manual_review.json` in the same folder and replace `ok` with `true` or `false`. The `note` field
   is recorded as the criterion's value: use it to justify.
4. Run `node js/cli.mjs evaluate --rescore` (or `node js/evaluate.mjs rescore results/<run>`). It does not collect again: it re-scores
   from `metrics.json` with the review, and the range narrows or closes. The report lists what remains.

Example `manual_review.json`:

```json
{
  "layers":     { "C2": { "ok": true,  "note": "Services receive repositories by injection; no layer imports another." } },
  "data_model": { "C2": { "ok": true,  "note": "order_items.unit_price is a documented price snapshot; no other copies." },
                  "C5": { "ok": true,  "note": "All ids are integers; naming is snake_case throughout." } }
}
```

You only need to include the criteria you decide; the others can be omitted or left as `null`.

## The judge (a model decides what is pending)

To get a result and not a range without reviewing each criterion by hand, a language model can decide the design-judgment
criteria: layers C2, cohesion C3, data model C1 to C6 and contracts C4 (only those that remain pending).

```
node js/cli.mjs evaluate --judge claude-opus-5-5          # inside the flow
node js/judge.mjs results/<run> --model claude-opus-5-5   # separately, on an already evaluated run
```

- **A model different from the generator.** `js/judge.mjs` refuses to run if the judge is the same model that generated the app (`meta.json`;
  names compared without provider prefix, date or bracket suffixes, and an alias such as `sonnet` matches any Sonnet), and also when the
  generator model was not recorded, because then it cannot be checked. `--allow-same-model` overrides both and it is recorded in `judge.json`.
- **Votes.** Each criterion is asked `--votes` times (3 by default) and the majority wins. An "I don't know" does not count; with no majority the
  criterion stays pending.
- **Priority.** manual review > automatic measurement > judge. The judge only fills what was still `null`.
- **Traceability.** `results/<run>/judge.json` stores the model, command, votes, justification and confidence of each decision.
  `profile.md` lists the criteria the judge decided and the range that would result without them.
- **Audit.** `judge.json` flags in `audit` the decisions a person must review: a sample (20%) and, always, those that
  were not unanimous or had low confidence. If you disagree, write it in `manual_review.json`: it wins over the judge.
- **Command.** By default it uses the Claude Code CLI (`claude -p --model {model}`, the prompt goes in through stdin): `claude` on the PATH or,
  if it is not there, the binary an editor extension installs (`~/.vscode/extensions/anthropic.claude-code-*/resources/native-binary`, the newest
  version). With `--cmd` you can use another (any program that reads the prompt from stdin and writes the answer to stdout).
- **One prompt per point.** The pending criteria of a point (for example data model C2 and C5) are asked in one prompt and decided
  consistently; each criterion still takes its own majority of the votes.

The judge does not decide what depends on a missing measurement: DL/PC (DV8), versions and vulnerabilities (network), tests (`--run-tests`),
duplicated literals (ESLint), unused dependencies and dead files (Knip) and duplication (jscpd). If those remain pending, the result will still
be a range, but a narrower one.

## Where values are read from (priority)

Manual review: `--manual` given to `js/evaluate.mjs` > `<app>/manual.json` > `results/<app>/manual_review.json`.

DV8 values (`dv8.DL`, `dv8.PC`, `dv8.unhealthy_inheritance`): the explicit value in the manual > `results/<app>/dv8/dv8_manual.json`
(human review, which no run overwrites) > `results/<app>/dv8/dv8_metrics.json` (computed). Use
`dv8_manual.json` to record a review, for example that of Unhealthy Inheritance:

```json
{ "unhealthy_inheritance": 0,
  "_review": { "conclusion": "AppError does not reference its subclasses and no file imports both the parent and a child." } }
```

## Explicit layer classification

If the directory heuristic does not reflect the architecture, create `<app>/.layers.json` with globs per layer and evaluate again:

```json
{ "presentation": ["backend/src/http/**"], "business": ["backend/src/services/**", "backend/src/domain/**"],
  "data": ["backend/src/repositories/**"], "shared": ["backend/src/errors.js", "backend/src/config.js"] }
```

`results/<app>/detected_layers.json` shows the layer each file received and the directory that decided it.
