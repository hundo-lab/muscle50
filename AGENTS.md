# muscle50 Agent Instructions

> **Claude Code:** where this file and `CLAUDE.md` disagree, follow `CLAUDE.md`.

## Start here

Before making any changes, read:

1. `docs/CURRENT_STATE.md`
2. `docs/HANDOFF.md`
3. relevant source files and tests for the current task

Then inspect the repository state:

```bash
git status
git log --oneline -10
git diff
```

Do not assume that previous chat context is available.

The repository is the source of truth.

## Working rules

* Preserve existing architecture unless there is a clear reason to change it.
* Read existing tests before modifying behavior.
* Prefer small, reviewable changes.
* Do not rewrite unrelated code.
* Run relevant tests after implementation.
* Run the project's lint/type-check commands when applicable.
* Do not claim work is complete unless you verified it.

## Session continuity

`docs/CURRENT_STATE.md` contains the durable project state.

`docs/HANDOFF.md` contains the latest session-specific handoff.

Before ending a substantial work session, update both files when necessary.

A handoff should include:

* what was attempted
* what was completed
* what remains
* files changed
* tests/checks run
* known failures or risks
* the recommended next action

Another agent may continue this work using a different model or provider, so never rely on conversation history alone.

## Git

Do not discard uncommitted work from another agent.

Before starting work, inspect:

```bash
git status
git diff
```

If previous work is incomplete, continue from the existing state unless the task explicitly requires reverting it.
