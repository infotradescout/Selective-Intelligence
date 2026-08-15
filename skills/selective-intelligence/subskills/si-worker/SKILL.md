---
name: si-worker
description: Do the real implementation work inside repo/code and keep edits aligned to the plan.
license: CC0-1.0
metadata:
  version: "0.1.0"
  parent: selective-intelligence
  audience: "plain-language"
---

# SI Sub-Skill: Worker

## What this skill does (plain language)
It builds or edits the project to match the plan.

## Inputs
- `si-planner` output packet
- Active repository files, issue state, and existing implementation

## Steps
1. Read the plan and current code.
2. Make only the edits needed for the active bounded deliverable. Do not absorb later deliverables into the run.
3. Keep code in canonical folders and avoid parallel duplicate paths.
4. Record what changed and what was skipped.
5. Return a short result packet with proof:
   - exact files touched
   - what behavior is now working
   - quick checks run

## Output
Return:
- `changed_files`
- `behaviors_enabled`
- `proof` (which behaviors were verified, what was checked, and the result)
- `open_failures` (if any)
- `next_skill`: `si-objector`

## Non-negotiable rules
- Match every changed behavior to the locked plan.
- Close only the active deliverable, never the whole discovered product.
- Never claim tests passed without proof.
- Avoid asking the user to do technical steps that can be done in code.
- Explain any technical point in plain, non-developer language.
