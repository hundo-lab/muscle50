---
name: feature-gate
description: Run the muscle50 quality gate (pytest, ruff check, mypy, git diff --check), ruff-format only the changed files that were already formatted, confirm LF line endings, and report in a fixed table. Use before any commit, when verifying a feature branch, and after integrating into main.
argument-hint: "[base ref, default: main]"
---

# muscle50 feature gate

Run this in the worktree you are checking, never in a different checkout. `$ARGUMENTS` is the base
ref to compare against (default `main`, meaning **local** main; see memory note "muscle50 local main
diverges from origin").

Sources: AGENTS.md "Working rules"; docs/CURRENT_STATE.md and docs/HANDOFF.md "Checks run" /
"Verification" sections (every feature since 2026-10-01 records exactly these four checks);
pyproject.toml `[tool.ruff]`, `[tool.mypy]`, `[tool.pytest.ini_options]`; user memory note
"muscle50 formatting and line endings".

## 1. Format only the changed files

The repo is only partly ruff-formatted. `presentation/terminal.py`, `application/refresh_garmin_activity.py`,
`domain/analytics.py`, `presentation/nutrition_terminal.py` and `infrastructure/sqlite/nutrition_repository.py`
are not formatted on main. **Never run `ruff format .` or `ruff format src`.** (Source: the memory note above and
docs/HANDOFF.md "Checks run" of Meal Edit, Food Fact Versioning and Meal Repeat.)

```bash
BASE=$(git merge-base HEAD main)   # replace main with the base ref argument when one was given
git diff --name-only --diff-filter=AM "$BASE" -- '*.py'   # changed tracked .py files
git ls-files --others --exclude-standard -- '*.py'        # new untracked .py files
```

For each file:
- **New file**: run `uv run --extra dev ruff format <file>`.
- **Existing file**: first check whether it was formatted at the base:
  `git show "$BASE:<file>" | uv run --extra dev ruff format --check --stdin-filename <file> -`
  - Exit 0 (it was formatted): run `uv run --extra dev ruff format <file>`.
  - Exit 1 (it was not formatted): do **not** format it. Keep your lines in the surrounding style and list
    the file under "format skipped".

The PostToolUse hook `.claude/hooks/post_edit_format.py` applies the same rule after every Edit/Write,
so this step usually finds nothing left to do. Run it anyway, because hooks do not see changes made by
scripts.

**Check-only mode (verifier, integrator on main):** do not write anything. Run
`uv run --extra dev ruff format --check <file>` for each file that would be formatted under the rules above.
Any "Would reformat" is a gate failure for the implementer to fix.

## 2. The four gates, in this order

Run all four even if one fails, so the report is complete.

| # | Gate | Command |
|---|------|---------|
| 1 | tests | `uv run --extra dev pytest` |
| 2 | lint | `uv run ruff check .` |
| 3 | types | `uv run mypy src tests` |
| 4 | whitespace | `git diff --check` (and `git diff --cached --check` if anything is staged) |

If `uv run ruff`/`uv run mypy` cannot find the tool (the environment was synced without the dev extra),
rerun that gate with `uv run --extra dev ...` and say so in the report.

## 3. Line endings

All tracked files are LF (`.gitattributes`: `* text=auto eol=lf`). Windows Python `write_text` writes CRLF
unless you pass `newline="\n"`.

```bash
git ls-files --eol -c -o --exclude-standard -- $(git diff --name-only "$BASE"; git ls-files --others --exclude-standard)
```

Every changed file must show `w/lf`; tracked files also show `i/lf`. `w/crlf` or `w/mixed` fails the gate.
Fix it by converting that file only.

## 4. Scope check

- `git status --short` and `git diff --stat "$BASE"` list only the files the plan or spec names.
- Unrelated reformatting or CRLF churn fails the gate. Revert those files and re-run.

## 5. Report (fixed format)

```markdown
### Gate report: <branch> @ <short sha> (base <base short sha>)

| # | Gate | Result | Detail |
|---|------|--------|--------|
| 1 | pytest | PASS/FAIL | <N passed, M failed / first failing test ids> |
| 2 | ruff check | PASS/FAIL | <rule codes + files, or "clean"> |
| 3 | mypy | PASS/FAIL | <"Success: no issues found in K source files" or first errors> |
| 4 | git diff --check | PASS/FAIL | <offending file:line> |
| 5 | LF | PASS/FAIL | <files not w/lf> |
| 6 | scope | PASS/FAIL | <unexpected files> |

- Formatted: <files> / Format skipped (not formatted at base): <files>
- Baseline: <last recorded count from docs/CURRENT_STATE.md "Verification", e.g. "917 passed, 118 files">
  -> now <counts>; new tests: <+n in which files>
- Overall: PASS only if rows 1-6 all PASS.
```

On failure, summarize the root cause in 1-3 lines per failing row (test name and assertion, rule and
location). Do not paste full logs. Do not "fix" failures by editing tests the spec did not ask you to
change: existing tests are behavior contracts (AGENTS.md "Read existing tests before modifying behavior").
