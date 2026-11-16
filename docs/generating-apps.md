# Generating the applications (step 1)

The evaluator receives applications that are already built. This guide describes how to produce them with an AI agent in a comparable way,
in two phases, and how to measure the **tokens** the agent consumes in each one. If you already have the applications, skip to "Usage" in the
[README](../README.md), but record their tokens first (section *Measuring the tokens*).

## The two phases

| Phase | What the agent does | Inputs it receives | Prompt |
|---|---|---|---|
| **initial** | Creates the project from scratch. | `technical-<level>.md` + `requirements-<domain>.md` | `combiner-prompt.md` with `{LEVEL}` and `{DOMAIN}` replaced, saved as `PROMPT.md` |
| **r2** | Implements the additional requirements on top of the project of phase initial, without rewriting it. | the project + `r2-additional-requirements.md` | `r2-prompt.md`, saved as `PROMPT-R2.md` |

The tokens of each phase are measured separately: the initial phase tells how much it costs the agent to **create** the application and the
r2 phase how much it costs to **modify** it, which is the operational side of maintainability the framework scores.

## What is in `specs/`

| File | Content |
|---|---|
| `requirements-ecommerce.md`, `requirements-cinema.md` | What the application must do in each domain (the same for all levels). |
| `technical-n1.md` | Level 1: PERN stack (PostgreSQL, Express, React, Node) only, layered monolith and delivery conditions. |
| `technical-n2.md` | Level 2: N1 plus expected quality attributes (understandable, modifiable, testable). |
| `technical-n3.md` | Level 3: N2 plus explicit architectural guidelines (SRP, dependency injection, unit tests, validation, documenting decisions). |
| `combiner-prompt.md` | Prompt of phase initial: combines a technical specification with the requirements. `{LEVEL}` is replaced by `n1`, `n2` or `n3` and `{DOMAIN}` by `ecommerce` or `cinema`. |
| `r2-additional-requirements.md` | Requirements of phase r2: documentation versioning (the R2 set goes in `docs/R2/`, with `README.md` and `entity-relationship-model.md`), Requirements 1–9, and the HTTP interface and environment variables that make them verifiable (`REPLICA_DATABASE_URL`, `SQLSERVER_URL`, `ADMIN_EMAIL`/`ADMIN_PASSWORD`, `AUDITOR_EMAIL`/`AUDITOR_PASSWORD`, `SEED_DATE`, `CANCELLATION_WINDOW_HOURS`, `SALES_CUTOFF_MINUTES`). |
| `r2-prompt.md` | Prompt of phase r2. It refers to the `technical-*.md`, `requirements-*.md` and `PROMPT.md` already in the app's folder. |

For another domain or another scale of levels, change these files and keep the names `technical-<level>.md` and `requirements-<domain>.md`.

## Golden rule: isolation

Each application is generated **with no context from the others**, so that one level does not influence another:

- A new, empty folder per application, named `<agent>-<domain>-<level>`, for example `apps/claude-ecommerce-n1`, `apps/claude-ecommerce-n2`,
  `apps/claude-ecommerce-n3` (the evaluator reads the agent, the domain and the level from the name).
- Phase initial: inside each one, only `requirements-<domain>.md`, **the** `technical-<level>.md` that corresponds to it and `PROMPT.md`.
- Phase r2: add `r2-additional-requirements.md` and `PROMPT-R2.md` to the same folder; nothing else changes.
- **A new agent session (no history) per application and per phase**, opened in that folder, with the text of the prompt and nothing else. Do
  not add hints or mention the rubric or the token measurement. The r2 session must not continue the initial one: a separate session is what
  makes the tokens of each phase separable, and it also means the agent has to understand the code it did not just write.
- Do not evaluate or open the results of another application until you have finished generating all of them.
- Do not leave the token records (`token-usage/`) or the results inside `apps/`: the agent of phase r2 would see them.

## Options for generating

**With an agent's CLI (recommended: it measures the tokens by itself).** `run_experiment.py` creates the folder, copies the specifications,
writes the prompt, launches the agent (`claude` or `codex` must be installed) with its machine-readable output and records the tokens of each
phase in `token-usage/<run_id>.json`:

```
python run_experiment.py --agent claude --level N1 --domain cinema --phase initial --model claude-sonnet-5-5 --skip-acceptance --skip-tests
python run_experiment.py --agent claude --level N1 --domain cinema --phase r2      --model claude-sonnet-5-5 --skip-acceptance --skip-tests
# or both phases in one go (each one in its own agent session)
python run_experiment.py --agent claude --level N1,N2,N3 --domain cinema --phase initial,r2 --model claude-sonnet-5-5
```

On Windows the script resolves `claude.cmd` / `codex.cmd` through `PATH` and sends the prompt on standard input (a multi-line argument
does not survive the `.cmd` wrappers). Generate **outside the repository** when you can (for example `--exp C:\temp\exp`): with
`--dangerously-skip-permissions` the agent can read any parent folder, including `rubric.json` and `specs/`.

**By hand.** Open the agent of your choice in each app's folder and paste the prompt (one session for initial, another for r2). Record the
tokens of each session when it finishes (next section).

**With subagents** (for example, from a Claude Code or Codex session): launch one subagent per application and phase, giving it only the
prompt and the working folder, and forbid it from reading outside it. Afterwards verify that there are no files outside each folder. Each
subagent keeps its own transcript, so its tokens can be recorded; the tokens of the orchestrating session are **not** attributed to any app.

## Measuring the tokens

The tokens are taken from the agents' own usage records, never from what the agent says about itself. `token_usage.py` reads them and
normalizes them so that Claude and Codex are comparable (input includes the prompt-cache reads and writes; output includes reasoning):

| Source | Where it is | How it is recorded |
|---|---|---|
| `run_experiment.py` | `experiments/<run>/agent.log` and `agent-r2.log` | automatically |
| Claude Code session or subagent | `~/.claude/projects/<project>/<session>.jsonl`, subagents in `<session>/subagents/agent-*.jsonl` | `scan` + `record --from` |
| Codex session or subagent | `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` | `scan` + `record --from` |
| `claude -p --output-format json` / `codex exec --json` run by hand | the output you saved | `record --from` |
| An interface that only shows totals | — | `record --input N --output N …` |

Steps, after generating (and again after phase r2):

1. `python token_usage.py scan` lists the Claude Code and Codex sessions on this machine that mention each app, with the phase it seems to
   belong to (r2 when the session works on `r2-additional-requirements.md`) and the suggested `record` commands. **Check each one**: a session
   that orchestrated several apps is shown as AMBIGUOUS and must not be recorded for any of them.
2. Record each phase of each app, for example:

   ```
   python token_usage.py record apps/claude-cinema-n1 --phase initial --from <transcript of the initial session>
   python token_usage.py record apps/claude-cinema-n1 --phase r2      --from <transcript of the r2 session>
   ```

   Pass several files when a phase took more than one session (a resumed session, a retry), or `--with-subagents` when you pass the transcript of a Claude Code session devoted to that
   app that delegated work to subagents. Recording a phase again replaces it (`--append` adds to it).
3. `python token_usage.py show` prints the table; `python cli.py evaluate` copies each record to `results/<run>/token_usage.json` and the
   report shows the section *AI token consumption* (initial, R2 and the R2 / initial ratio). The comparison (`results/_comparison/`) adds the
   columns `tokens_initial_*`, `tokens_r2_*` and `tokens_r2_vs_initial`.

Record the tokens as soon as each phase ends: the agents' local transcripts can be rotated or deleted, and then the figure cannot be
reconstructed.

## Delivery conditions the evaluator expects

`backend/` and `frontend/` at the root, each with a `package.json`, installable with `npm install` and runnable with
`npm start`; the backend reads its port from `PORT` and the PostgreSQL connection string from `DATABASE_URL`; a `docker-compose.yml` at the root that
starts PostgreSQL; a `README.md` with instructions; and `docs/entity-relationship-model.md` with a Mermaid `erDiagram` that matches the implemented schema
(criterion C6 and the *Entity-relationship model* artifact). The backend must create its schema when it starts (the generated specs say how). If
`backend/` or `frontend/` is missing, the package and test analysis will not see that part; if no SQL file, Sequelize migration or Sequelize model defines the
schema, the *Data model design* point is not evaluable.

## Afterwards

1. Note the **model** that generated the applications: `--model` is required (the evaluator refuses to run without it unless you pass
   `--allow-missing-model`, in which case the reports carry a warning).
2. Check that the tokens of both phases are recorded (`python token_usage.py show`); `cli.py evaluate` warns about every app that lacks one.
3. Run `python cli.py doctor` and then `python cli.py evaluate`. The evaluation measures the state of the code when it runs: to keep the
   evaluation of the state after phase initial, evaluate before phase r2 with another `--results` folder.
4. Optional: to know whether the application really works, use the acceptance gate. `run_experiment.py` starts PostgreSQL from the
   application's own `docker-compose.yml` (project and disposable database `eval_<run>`, removed afterwards), runs the backend with
   `DATABASE_URL` and `PORT`, and checks the minimum HTTP interface of the domain with `acceptance_check.py --domain <domain>`:
   e-commerce (money as JSON numbers, opaque ids, the volume-discount examples, the stock rules, the order statuses) or cinema (the seed
   screenings and prices, the seat map, locks between users, sold seats, isolation of purchases). The suites cover the **original**
   requirements, so the gate runs right after phase initial, before r2; on a project that already implements r2 it is skipped and
   the earlier result is kept. It needs Docker; without it the gate is skipped and says so. Or test the application by hand.
