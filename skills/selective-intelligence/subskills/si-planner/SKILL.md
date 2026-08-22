---
name: si-planner
description: Use only when a selected Selective Intelligence Council is locking a whole product, architecture, migration, or other consequential plan.
license: CC0-1.0
metadata:
  version: "0.1.1"
  parent: selective-intelligence
  audience: "plain-language"
---

# SI Sub-Skill: Planner

## What this skill does (plain language)
It locks a consequential Council plan. Clear bounded work does not invoke this role or wait for a plan lock.

## Inputs
- `si-intake` output packet
- Repository or project context if available

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
