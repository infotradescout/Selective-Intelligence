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
2. Confirm the whole product remains preserved while only one end-to-end deliverable is active.
3. Challenge execution-window fit and reject Sites as the primary target when operational data, permissions, backend workflows, repository integration, or multi-stage logic carry the production value.
4. Verify claims with evidence.
5. List missing work, weak evidence, drift, and scope skips.
6. Mark each finding with severity and exact place.
7. Recommend the smallest fix for each block.

## Output
Return:
- `findings` (numbered list with severity + evidence)
- `pass` / `sustained` / `partial` / `blocked`
- `next_skill`: `si-aligner`

## Non-negotiable rules
- No style-only policing.
- No invented success claims.
- No new scope that was not in the lock unless called out as a needed follow-up.
- Treat unbounded execution, layer-only slices, erased later deliverables, and convenient-target adoption as blocking adoption defects.
- Use plain language for all findings and why they matter.
