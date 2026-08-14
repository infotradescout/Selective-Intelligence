---
name: si-aligner
description: Merge planner intent, worker work, and objector findings into one truthful aligned result.
license: CC0-1.0
metadata:
  version: "0.1.0"
  parent: selective-intelligence
  audience: "plain-language"
---

# SI Sub-Skill: Aligner

## What this skill does (plain language)
It decides: Is the work true, complete, and still following the original goal?

## Inputs
- `si-planner` packet
- `si-worker` packet
- `si-objector` findings

## Steps
1. Match each finding back to the plan and evidence.
2. Keep findings that are real and block truth.
3. Return to Worker only when correction is needed.
4. If all checks pass, mark gate status:
   - `aligned` / `provisionally_aligned` / `blocked`.
5. Hand off final packet to verifier.

## Output
Return:
- `alignment_status`
- `open_findings`
- `approved_to_resume` (true/false)
- `next_skill`: `si-verifier` (or `si-worker` if blocked)
- `required_corrections` (if any)

## Non-negotiable rules
- Do not use vote counts as proof.
- Never close a blocked issue.
- Explain the decision in simple, plain language with one-line proof references.
