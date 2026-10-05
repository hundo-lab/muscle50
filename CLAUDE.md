@AGENTS.md

# muscle50 - Claude Code rules

Where AGENTS.md (imported above, shared with other tools) and this file disagree, this file wins.
Project overview: `docs/PROJECT_CONTEXT.md` when present.
Product goal and feature priorities: `docs/goals.md`. Pick and design features against it.

## Quality gate (run in this order, all four, before any commit)

```bash
uv run --extra dev pytest
uv run ruff check .
uv run mypy src tests
git diff --check
```

The `feature-gate` skill runs these, formats only changed files that were already formatted, checks
LF, and reports in a fixed table. Never run `ruff format .` or `ruff format src`.

## Records (replaces AGENTS.md "Session continuity")

- `docs/CURRENT_STATE.md` and `docs/HANDOFF.md` are **frozen** history as of 2026-10-05. Do not update them.
- The durable record is: integrated specs (`docs/specs/<id>.md`, which include limits and follow-up
  candidates), feature docs (`docs/<feature>.md`, which include known issues), `README.md`, and commit messages.
- Live progress of `/feature` runs (status, reserved migrations, integration lock) is in
  `.git/muscle50-orchestration/` via `.claude/scripts/feature_state.py`. It is never committed.

## Orchestration (parallel by default)

- Start feature work with `/feature <spec> [<spec> ...]`; several specs, or several sessions, run in parallel.
  Specs come from `docs/specs/_TEMPLATE.md`; the flow is in `docs/specs/README.md`.
- Agents: `designer` (read-only plan), `implementer` (code, tests, `docs/<feature>.md` in its own Paseo
  worktree on `feature/<id>`), `verifier` (independent check, no edits), `integrator`.
- Only the orchestrator assigns migration numbers (`feature_state.py reserve-migration`). Only the
  integrator edits `README.md` and commits a spec's final frontmatter.
- Integration happens one at a time under the integration lock: rebase `feature/<id>` onto **local**
  main, re-run the gate, then `git merge --ff-only`. Never rebase main, never merge commits, squash or force.

## Human gates (agents stop and ask)

1. **Design approval**: after the designer's plan, before any branch or code.
2. **Integration approval**: after the verifier's PASS, before the feature is rebased and fast-forwarded into local main.
3. **Production migration**: applying a new migration to `%LOCALAPPDATA%\muscle50` (back up, apply, verify).
4. **Live Garmin verification** of a feature that changes Garmin sync.
5. **Push**: the user runs `git push`.

## Running muscle50 and safety hooks (`.claude/settings.json`)

- Claude may run `uv run muscle50 ...` against production **from the main checkout**: for example `daily`,
  `recommend` or `nutrition log` when the user asks. Feature worktrees, tests and smoke runs use a temporary
  `MUSCLE50_HOME="$TEMP/muscle50-<name>"`.
- PreToolUse (`.claude/hooks/pre_bash_guard.py`) blocks:
  - `git push`;
  - direct writes or deletes under `%LOCALAPPDATA%\muscle50`;
  - `muscle50` against production from non-main code, or while a migration in main is not yet applied
    to production (that is gate 3).
- PostToolUse (`.claude/hooks/post_edit_format.py`): CRLF to LF, and ruff format on the edited `.py` file when it is
  new or was already formatted at HEAD.
- Hooks run with the project's `.venv` Python, falling back to `python` on PATH. If the guard cannot run, it blocks
  every shell command (fail closed) until that is fixed.
