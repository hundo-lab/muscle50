---
description: Run one muscle50 feature end to end from a spec - reserve a migration number, design (stops for your approval), implement in a Paseo worktree, verify (up to 3 rejections), integrate into local main, and report the remaining human gates.
argument-hint: "<docs/specs/<id>.md>"
disable-model-invocation: true
---

# /feature $ARGUMENTS

You are the **orchestrator**. You coordinate the agents `designer`, `implementer`, `verifier` and
`integrator`. You write nothing but spec frontmatter (`status`, `migration`) and your messages to the
user. You never edit code, tests, feature docs or the state documents yourself.

Run this from the **main checkout** (the worktree on `refs/heads/main`). Flow and rules:
`docs/specs/README.md`, `CLAUDE.md`.

## 1. Read the spec

- `$ARGUMENTS` must be a file under `docs/specs/` other than `_TEMPLATE.md` and `README.md`. If it is not,
  stop and say so.
- Read its frontmatter: `id`, `title`, `status`, `migration`, `output_change`, `user_gates`. The slug is
  `id`, and the branch will be `feature/<id>`.
- `status`:
  - `draft` or `approved`: continue.
  - `in-progress` or `verified`: tell the user what exists (`git branch --list feature/<id>`,
    `git worktree list`) and ask whether to resume from step 5 or 6. Do not start over.
  - `integrated`: stop, there is nothing to do.
- Check that the required sections exist: purpose, scope / non-goals, command examples, rules, acceptance
  criteria. If any is empty, list the gaps and stop.

## 2. Migration number (only the orchestrator assigns numbers)

Assign a number when the spec already says `reserved:NNN` (validate it) or when the approved design
needs a migration (step 3).

1. Find the highest existing number:
   - `git ls-tree --name-only main src/muscle50/infrastructure/sqlite/migrations/`
   - each local branch: `git for-each-ref --format='%(refname:short)' refs/heads`, then the same `ls-tree`
     per branch (an unmerged branch may already hold a number)
   - every `docs/specs/*.md` in the main checkout: `migration: reserved:NNN`
2. Next number = the highest of all of these + 1, as three digits. A spec that already says `reserved:NNN`
   is valid only if no other spec or branch uses NNN.
3. Write `migration: reserved:NNN` into this spec's frontmatter in the main checkout, and tell the user.
   (The `INSERT OR IGNORE` marker hides a duplicate number silently; that happened with 006. See the
   `add-migration` skill.)

## 3. Design, then STOP for approval (human gate 1)

- Call the `designer` agent with the spec path and this instruction: "Design per your instructions.
  Output only the plan."
- If the plan says a migration is needed and none is reserved, do step 2 now and add the number to the
  plan.
- Show the user the plan, or the alternatives when the designer gave 2-3 of them, and ask for approval:
  approve / approve with changes / choose an alternative / reject.
- **End your turn here and wait.** Do not create a worktree, branch or any code before an explicit
  approval. A hard or looping design question can go to `/paseo-committee` (user-invoked).
- On approval: write `status: approved` to the spec and keep the approved plan text, including the
  user's changes, for the next steps.

## 4. Worktree and implementation

1. Create the worktree the Paseo way (see the `paseo` skill, "Workspaces" / "CLI semantics"):

   ```bash
   paseo workspace create --isolation worktree --mode branch-off --new-branch feature/<id> \
     --base refs/heads/main --worktree-slug <id> --title "feature/<id>" --json
   ```

   Use the `cwd` from the JSON as `<worktree>`. `refs/heads/main` means local main on purpose. If `paseo`
   is not available, use `git worktree add -b feature/<id> <path> main` and tell the user.
2. Write `status: in-progress` to the spec.
3. Call the `implementer` agent with: `<worktree>`, the branch, the spec path, the reserved migration (or
   `none`), `output_change`, and the full approved plan.

## 5. Verification loop (at most 3 rejections)

- Call the `verifier` agent with: `<worktree>`, the branch, the spec path, the approved plan and the
  implementer's report. Use a new verifier each round, so it never shares the implementer's context.
- On **REJECT**: send the numbered findings back to the implementer (continue the same implementer agent
  if you can address it, otherwise start a new `implementer` with the plan and the findings), then verify
  again.
- After the **3rd rejection**, stop. Report every round's findings and what changed between rounds, and
  ask the user how to proceed. Do not integrate.
- On **PASS**: write `status: verified` to the spec.

## 6. Integration

Call the `integrator` agent with: the branch, `<worktree>`, the spec path, the plan, the implementer's
report and the verifier's PASS report. It fast-forwards local main, re-runs the gate, updates the state
documents and commits the docs. It never pushes. If it stops at a pre-check (main moved, dirty main, gate
failed on main), relay that to the user and stop.

## 7. Final report

Make sure the spec says `status: integrated` (the integrator commits it). Then report:

- the feature, the branch, and the commits on main (`<old>..<new>`) including the docs commit
- the gate results (feature branch and main) and the verification summary
- the files changed, grouped as code / tests / docs
- **Remaining human gates**, as a checklist with exact steps:
  - [ ] production migration NNN (if reserved): back up, apply, verify (`add-migration` section 6)
  - [ ] live Garmin verification (if the feature touches Garmin sync): commands to run, expected result
  - [ ] push: `git push origin main` (the user runs it; agents are blocked from pushing)
- known risks and limitations, and the recommended next action
