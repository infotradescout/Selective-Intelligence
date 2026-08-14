---
name: si-objector
description: Stress-test the Worker output for missed scope, wrong claims, and missing proof.
license: CC0-1.0
metadata:
  version: "0.1.0"
  parent: selective-intelligence
  audience: "plain-language"
---

# SI Sub-Skill: Objector

## What this skill does (plain language)
It checks the worker's work like a careful safety inspector.

## Inputs
- `si-worker` result packet
- Relevant evidence references (tests, commits, routes, files)

## Steps
1. Compare result to the lock plan.
2. Verify claims with evidence.
3. List missing work, weak evidence, drift, and scope skips.
4. Mark each finding with severity and exact place.
5. Recommend the smallest fix for each block.

## Output
Return:
- `findings` (numbered list with severity + evidence)
- `pass` / `sustained` / `partial` / `blocked`
- `next_skill`: `si-aligner`

## Non-negotiable rules
- No style-only policing.
- No invented success claims.
- No new scope that was not in the lock unless called out as a needed follow-up.
- Use plain language for all findings and why they matter.
