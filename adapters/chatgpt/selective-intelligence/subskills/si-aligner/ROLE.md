---
name: si-aligner
description: Use only when a selected Selective Intelligence Council has conflicting Worker and reviewer findings that require an independent disposition.
---

# SI Sub-Skill: Aligner

## What this skill does (plain language)
It resolves a real conflict between Council findings. Do not invoke it for ordinary work or findings the parent context can reconcile directly.

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
