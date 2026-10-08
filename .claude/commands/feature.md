---
description: Run muscle50 features end to end from one or more specs, in parallel - design (stops for approval), implement in Paseo worktrees, verify (up to 3 rejections), stop for integration approval, integrate one at a time into local main, and report the remaining human gates.
argument-hint: "<docs/specs/<id>.md> [<docs/specs/<id2>.md> ...]"
disable-model-invocation: true
---

# /feature $ARGUMENTS

You are the **orchestrator** for one or more features. You coordinate the `designer`, `implementer`,
`verifier` and `integrator` agents. You write only runtime state (through the helper below), the spec
commit in step 3, and your messages to the user. You never edit code, tests or docs.

Run this from the **main checkout** (the worktree on `refs/heads/main`). Rules: `CLAUDE.md`. Flow:
`docs/specs/README.md`.

Runtime state helper (shared by every session and worktree, never committed):

```bash
python .claude/scripts/feature_state.py set <id> status=<status> [key=value ...]
python .claude/scripts/feature_state.py get <id> | list | dir | reserve-migration <id> | release-migration <id>
python .claude/scripts/feature_state.py lock <id> --wait 900 | unlock <id>
```

Statuses: `designing` -> `awaiting-design-approval` -> `approved` -> `in-progress` -> `verifying` ->
`awaiting-integration-approval` -> `integrating` -> `integrated` (or `blocked`).

**Parallelism.** Handle every spec in `$ARGUMENTS` at once. Put independent agent calls for different
features in the same message, so designers run in parallel, then implementers, then verifiers. Ask for
approvals in batches. Integrations are serialized by the lock. Other `/feature` sessions may be running
too: always read and write state through the helper, never assume you are alone.

## 1. Read the specs

For each path:
- It must be a file under `docs/specs/` other than `_TEMPLATE.md` and `README.md`. The `id` comes from the
  frontmatter (kebab-case); the branch will be `feature/<id>`.
- Check the runtime state (`get <id>`):
  - empty, or `designing` with nothing on disk: continue.
  - any later status: tell the user what exists (`git branch --list feature/<id>`, `git worktree list`)
    and resume from the matching step. Do not start over.
  - `integrated`, or committed frontmatter `status: integrated`: skip it.
- The required sections must have content: purpose, scope / non-goals, command examples, rules,
  acceptance criteria. If any is empty, report the gaps for that spec and drop it from this run.
- Run `set <id> status=designing spec=<path>`.

## 2. Design (parallel), then STOP for approval (human gate 1)

- Call one `designer` per spec, in parallel. Tell each one about the other features in this run and in
  `feature_state.py list`, so it can flag overlapping files or migrations.
- If a plan needs a migration: `reserve-migration <id>` and add the printed `NNN` to that plan. The helper
  checks every branch, every worktree and every reservation, and is atomic.
- Save each designer's plan **verbatim and in full** (not a summary) to `<state dir>/plans/<id>.md`
  (`feature_state.py dir` prints the state directory), so a later session can resume and the implementer gets
  the whole plan. Then run `set <id> status=awaiting-design-approval`.
- Show the user all plans (or the 2-3 alternatives a designer gave). Number the features and ask, per
  feature: approve / approve with changes / choose an alternative / reject.
- **End your turn and wait.** Create no branch, worktree or code before an explicit approval. For a hard
  design question, suggest `/paseo-committee`.
- On reject: `release-migration <id>` and `set <id> status=blocked`.

## 3. After design approval: commit the spec, create the worktree, implement (parallel)

For each approved feature:
1. Append the user's changes to the saved plan, then `set <id> status=approved`.
2. The spec must be committed on main **before** branching. If `git ls-files --error-unmatch <spec>` fails,
   or the spec has uncommitted changes, take the lock (`lock <id> --wait 900`), run
   `git add <spec> && git commit -m "docs: add spec <id>"` (that path only, attribution trailer if
   configured), then `unlock <id>`.
3. Create the worktree the Paseo way (see the `paseo` skill):

   ```bash
   paseo workspace create --isolation worktree --mode branch-off --new-branch feature/<id> \
     --base refs/heads/main --worktree-slug <id> --title "feature/<id>" --json
   ```

   Use the JSON `cwd` as `<worktree>`. If `paseo` is missing, use `git worktree add -b feature/<id> <path> main`
   and say so. Run `set <id> status=in-progress branch=feature/<id> worktree=<worktree>`.
4. Call the `implementer` agents in parallel. Each gets `<worktree>`, its branch, the spec path, its
   migration (`reserved:NNN` or `none`), `output_change`, and the full approved plan.

## 4. Verification loop (per feature, at most 3 rejections)

- When an implementer reports, run `set <id> status=verifying` and call a **new** `verifier` with
  `<worktree>`, the branch, the spec, the approved plan and the implementer's report.
- **REJECT**: send the numbered findings to the implementer (continue the same agent if possible,
  otherwise start a new `implementer` with the plan plus the findings), then verify again. After the
  3rd rejection, `set <id> status=blocked`, report every round, and stop that feature. The others continue.
- **PASS**: run `set <id> status=awaiting-integration-approval verified_sha=<sha>`.

## 5. STOP for integration approval (human gate 2)

When one or more features are awaiting integration approval, show for each:
- `git diff --stat main...feature/<id>` and the commits
- the verifier's gate table and acceptance-criteria table
- whether it adds a migration (gate 3 follows) or touches Garmin sync (gate 4 follows)
- other features that change the same files (a rebase conflict is possible)

Ask: integrate / hold / send back with comments. **End your turn and wait.** Features that were sent back
go to the implementer with the comments, then through step 4 again.

## 6. Integration (one at a time)

For each approved feature, in the order the user approved them, call the `integrator` with: the
branch, `<worktree>`, the spec path, the approved plan, and the implementer's and verifier's reports. It
takes the lock, rebases onto local main, re-runs the gate, commits the README and final spec frontmatter,
fast-forwards main, and releases the lock. It never pushes.

- **Push** (not a human gate): when the integrator reports success, run `git push origin main` from the main
  checkout. Only a plain fast-forward push; the hook blocks force, delete and mirror. If origin rejects it
  (origin moved), stop and report: never force or rewrite. With several features in one run you may push
  once after the last integration.

- **Rebase conflict** (the integrator aborted the rebase): send it to the implementer with the instruction
  "rebase feature/<id> onto local main, resolve the conflicts preserving both features' behaviour, re-run
  the gate". Then verify again (step 4) and ask for integration approval again (step 5): the content changed.
- Main moved during integration, or the gate failed after the rebase: relay this and follow the
  integrator's recommendation.

## 7. Final report

Per feature: status, branch, commits on main (`<old>..<new>`), gate results, files changed (code / tests
/ docs). Then a **remaining human gates** checklist with exact steps:
- [ ] production migration NNN (if any): back up, apply, verify (`add-migration` section 6)
- [ ] live Garmin verification (if the feature touches Garmin sync): commands and expected result

Report the push as done (`origin/main` sha) or, if origin rejected it, the error and what the user should do.

Also report blocked features with their reasons, and the recommended next action.
