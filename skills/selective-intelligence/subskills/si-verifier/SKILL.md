---
name: si-verifier
description: Use only when Selective Intelligence explicitly assigns fresh-context verification for high-risk, self-referential, or repeatedly failed work.
license: CC0-1.0
metadata:
  version: "0.1.1"
  parent: selective-intelligence
  audience: "plain-language"
---

# SI Sub-Skill: Verifier

## What this skill does (plain language)
It independently checks one bounded result and returns a short evidence-backed verdict. Ordinary work uses proportional validation in the parent context.

## Inputs
- `si-aligner` alignment packet
- Latest evidence from code or repository state

## Steps
1. Confirm the top risks and proof are still true.
2. Check one final time that the result is deploy-safe for the claimed scope.
3. Write a short handoff with:
   - what changed
   - what is proven
   - what is still blocked
   - next safe user step (if any)
4. Save a concise resume-style packet for continuity.

## Output
Return:
- `resume_packet`
- `final_status` (`done` / `blocked` / `partial`)
- `user_explanation` (plain language)
- `remaining_blockers` (if any)
- `next_safe_step`

## Non-negotiable rules
- Never claim complete if proof is missing.
- If no deploy/live proof exists, say so plainly.
- Keep the user explanation short and plain.
