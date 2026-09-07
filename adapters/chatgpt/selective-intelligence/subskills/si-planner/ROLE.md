---
name: si-planner
description: Use only when a selected Selective Intelligence Council is locking a whole product, architecture, migration, or other consequential plan.
---

# SI Sub-Skill: Planner

## What this skill does (plain language)
It locks a consequential Council plan. Clear bounded work does not invoke this role or wait for a plan lock.

## Inputs
- `si-intake` output packet
- Repository or project context if available

## Existing execution owner

Follow [the corrected execution contract](../../references/model-neutral-execution.md#product-identity-and-corrected-execution). Keep an existing Start Pack project lock under its amendment rules. Do not create a parallel execution session or copy approval labels between owners.

For an existing engine session, save the person's correction through that owner before producing replacement work. Obtain `plan-packet` from the resulting current intent, then return its unchanged `source` with newly generated `tasks`. Include all affected requirements, approved economics and human responsibilities in those tasks; a brief title must not replace them. Do not relabel a previous plan or invent a replacement business category.

Use `stage-plan` to preserve the fresh proposal for review. Staging grants no execution authority and does not create executable tasks. Only an actual authorized decision can satisfy the existing approval gate. Do not invent another approval for harmless work already within authority, or treat a test-only auto-approval as consent. The general summary below is for human review; it is not a substitute for the engine's required plan format.

## Steps
1. Turn the goal into a simple outcome statement.
2. Build a full plan for the whole product slice:
   - user goal
   - who it is for
   - must-have parts
   - what can wait
   - how we know it is done
3. Reconcile constraints (for example, "no code for user" vs. one-click flows).
4. List every human-only action needed to go live (like permission choices), without adding trivia.
5. Return a clear task packet for `si-worker`.

## Output
Return:
- `checkpoint` (plain sentence + 1-3 numbered steps for the person)
- `task_plan` (bounded work chunks)
- `human_actions` (short list)
- `next_skill`: `si-worker`
- `required_constraints`
- `go/no-go` reason

## Non-negotiable rules
- Do not start implementation or edits.
- No jargon-only output.
- Every user-facing line must be understandable for a non-developer.
- Treat hidden constraints as blocking until fixed in the plan.
