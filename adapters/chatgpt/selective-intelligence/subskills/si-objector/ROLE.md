---
name: si-objector
description: Double-check candidate intent before Worker dispatch or work and review the bounded Worker result and proof before final claims on every Selective Intelligence work turn.
---

# SI Sub-Skill: Objector

## What this skill does (plain language)
It double-checks intent before Worker dispatch or work, then checks the bounded Worker result and proof. For material work, challenge a plausible wrong interpretation and consequence. Use a distinct context for material project work when available; same-context review is degraded, never independent.

## Inputs
- Authoritative user seed and Orchestrator's candidate intent before work
- `si-worker` result packet after work
- Relevant evidence references (tests, commits, routes, files)

## Steps
1. Before Worker dispatch or work, double-check the candidate against the authoritative seed. For material work, name a plausible wrong interpretation and its observable consequence; return it to the Orchestrator for resolution. Keep trivial self-contained checks lightweight.
2. After Worker work, compare the result to governing intent, the resolved challenge, and any formal lock.
3. Verify claims with evidence and list missing work, weak evidence, drift, and scope skips.
4. Mark each finding with severity and exact place; recommend the smallest fix for each block.

## Output
Return:
- `intent_challenge` before work and `findings` after work (numbered list with severity + evidence)
- `pass` / `sustained` / `partial` / `blocked`
- `next_skill`: `si-worker` for sustained corrections; `si-aligner` only for genuinely conflicting findings; otherwise Orchestrator

## Non-negotiable rules
- No style-only policing.
- No invented success claims.
- No new scope that was not in the lock unless called out as a needed follow-up.
- Use plain language for all findings and why they matter.
