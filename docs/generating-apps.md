# Generating the applications (step 1)

The evaluator receives applications that are already built. This guide describes how to produce them with an AI agent in a comparable way.
If you already have the applications, skip to "Usage" in the [README](../README.md).

## What is in `specs/`

| File | Content |
|---|---|
| `requirements-ecommerce.md` | What the application must do (the same for all levels). |
| `technical-n1.md` | Level 1: MERN stack only, layered monolith and delivery conditions. |
| `technical-n2.md` | Level 2: N1 plus expected quality attributes (understandable, modifiable, testable). |
| `technical-n3.md` | Level 3: N2 plus explicit architectural guidelines (SRP, dependency injection, unit tests, validation, documenting decisions). |
| `combiner-prompt.md` | The prompt that combines a technical specification with the requirements. `{LEVEL}` is replaced by `n1`, `n2` or `n3`. |

For another domain or another scale of levels, change these files and keep the name `technical-<level>.md`.

## Golden rule: isolation

Each application is generated **with no context from the others**, so that one level does not influence another:

- A new, empty folder per application, for example `apps/claude-n1`, `apps/claude-n2`, `apps/claude-n3`.
- Inside each one, only `requirements-ecommerce.md` and **the** `technical-<level>.md` that corresponds to it.
- A new agent session (no history), opened in that folder, with the text of `combiner-prompt.md`
  (`{LEVEL}` replaced) and nothing else. Do not add hints or mention the rubric.
- Do not evaluate or open the results of another application until you have finished generating all of them.

## Options for generating

**By hand.** Open the agent of your choice in each app's folder and paste the prompt. It is the simplest and requires
no extra tools.

**With an agent's CLI.** `run_experiment.py` creates the folder, copies the specifications and launches the agent
(`claude` or `codex` must be installed):

```
python run_experiment.py --agent claude --level N1 --skip-acceptance --skip-tests
```

**With subagents** (for example, from a Claude Code session): launch one per level, giving it only the prompt and the
working folder, and forbid it from reading outside it. Afterwards verify that there are no files outside each folder.

## Delivery conditions the evaluator expects

`backend/` and `frontend/` at the root, each with a `package.json`, installable with `npm install` and runnable with
`npm start`; a `README.md` with instructions. If either is missing, the package and test analysis will not see that part.

## Afterwards

1. Note the **model** that generated the applications: `--model` will ask for it.
2. Run `python cli.py doctor` and then `python cli.py evaluate`.
3. Optional: to know whether the application really works, use the acceptance gate. `run_experiment.py` starts PostgreSQL from the
   application's own `docker-compose.yml` (project and disposable database `eval_<run>`, removed afterwards), runs the backend with
   `DATABASE_URL` and `PORT`, and checks the minimum HTTP interface of `specs/requirements-ecommerce.md` with `acceptance_check.py`
   (money as JSON numbers, opaque integer or UUID ids, the volume-discount examples, the stock rules). It needs Docker; without it the
   gate is skipped and says so. Or test the application by hand.
