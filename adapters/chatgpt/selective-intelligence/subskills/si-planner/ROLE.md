---
name: si-planner
description: Create the first-checkpoint plan in plain language, then hand exact tasks to the build agent.
license: CC0-1.0
metadata:
  version: "0.1.0"
  parent: selective-intelligence
  audience: "plain-language"
---

# SI Sub-Skill: Planner

## What this skill does (plain language)
It locks the plan before any building.

## Inputs
- `si-intake` output packet
- Repository or project context if available

## Steps
1. Turn the goal into a simple outcome statement.
2. Map the complete discovered product, then choose one first deliverable that is a complete user loop and fits the current execution window:
   - user goal
   - who it is for
   - full product capabilities and dependency order
   - the active deliverable's entry, ending, required parts, and proof
   - later deliverables that remain preserved
3. Choose the execution target from the operating needs. Prefer a fitting established repository for operational products; do not default to Sites when persistent data, permissions, backend workflows, repository integration, or multi-stage logic carry the value.
4. Reconcile constraints (for example, "no code for user" vs. one-click flows).
5. List every human-only action needed to go live (like permission choices), without adding trivia.
6. Validate the boundary and target with `scripts/execution_contract.py`, then return one active task packet for `si-worker`.

## Output
Return:
- `checkpoint` (plain sentence + 1-3 numbered steps for the person)
- `task_plan` (bounded work chunks)
- `later_deliverables` (ordered outcomes, not active work)
- `execution_target` (selected environment + plain reason)
- `human_actions` (short list)
- `next_skill`: `si-worker`
- `required_constraints`
- `go/no-go` reason

## Non-negotiable rules
- Do not start implementation or edits.
- Preserve the complete product definition, but activate only one end-to-end deliverable.
- Derive the phase boundary without asking the person to split the product.
- No jargon-only output.
- Every user-facing line must be understandable for a non-developer.
- Treat hidden constraints as blocking until fixed in the plan.
