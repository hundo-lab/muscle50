@AGENTS.md

# muscle50 - Claude Code notes

AGENTS.md (imported above) is the shared rulebook for every coding agent. Keep it unchanged here. This
file adds only the Claude Code orchestration layer. Project overview: `docs/PROJECT_CONTEXT.md` when it
exists; durable state: `docs/CURRENT_STATE.md`.

## Quality gate (run in this order, all four, before any commit)

```bash
uv run --extra dev pytest
uv run ruff check .
uv run mypy src tests
git diff --check
```

The `feature-gate` skill runs these, formats only changed files that were already formatted, checks
LF, and reports in a fixed table. Never run `ruff format .` or `ruff format src`.

## Orchestration

- Start feature work with `/feature <docs/specs/<id>.md>`. Write the spec from
  `docs/specs/_TEMPLATE.md`; the flow is in `docs/specs/README.md`.
- Agents (`.claude/agents/`): `designer` (read-only plan), `implementer` (code + tests + `docs/<feature>.md`
  in the feature worktree), `verifier` (independent check, no edits), `integrator` (ff-only into local
  main + state docs).
- Only the **integrator** edits `docs/CURRENT_STATE.md`, `docs/HANDOFF.md` and `README.md`. This keeps
  parallel feature branches from conflicting.
- Only the **orchestrator** (`/feature`) assigns migration numbers. It records them in the spec
  frontmatter as `migration: reserved:NNN`; implementers use that number and no other.
- Feature work happens in a Paseo worktree on `feature/<id>`, branched from **local** main. Integration is
  fast-forward only: no merge commits, rebase, squash or amend. Branches and worktrees are kept.
- Skills: `domain-principles` (data and output rules), `feature-gate`, `add-cli-command`, `add-migration`.
  Paseo skills (`paseo`, `paseo-handoff`, `paseo-advisor`, `paseo-committee`) cover workspaces, handoffs
  and second opinions. Do not duplicate them.

## Human gates (agents stop and ask; never do these themselves)

1. **Design approval**: `/feature` stops after the designer's plan until the user approves.
2. **Production migration**: applying a migration to `%LOCALAPPDATA%\muscle50` (backup, apply, verify).
3. **Live Garmin verification**: anything that logs in to Garmin (MFA is interactive).
4. **Push**: `git push` is run by the user.

## Safety hooks (`.claude/settings.json`)

- PreToolUse (Bash/PowerShell), `.claude/hooks/pre_bash_guard.py`, blocks: `git push`; writes or deletes
  under `%LOCALAPPDATA%\muscle50`; and the `muscle50` CLI unless `MUSCLE50_HOME` points at a temporary home,
  e.g. `MUSCLE50_HOME="$TEMP/muscle50-smoke" uv run muscle50 ...`.
- PostToolUse (Edit/Write/MultiEdit), `.claude/hooks/post_edit_format.py`: converts CRLF back to LF and
  ruff-formats the edited `.py` file only if it was already formatted at HEAD.
- Hooks are a safety net, not permission to try risky commands. They need `python` (3.9+) on PATH.
