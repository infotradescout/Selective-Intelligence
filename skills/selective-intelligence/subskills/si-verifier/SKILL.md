---
name: si-verifier
description: Final-check the result and produce a short, plain-language handoff for the person.
license: CC0-1.0
metadata:
  version: "0.1.0"
  parent: selective-intelligence
  audience: "plain-language"
---

# SI Sub-Skill: Verifier

## What this skill does (plain language)
It gives the final "done" or "not done" message in simple words.

## Inputs
- `si-aligner` alignment packet
- Latest evidence from code or repository state

## Steps
1. Confirm the top risks and proof are still true.
2. Check one final time that the active deliverable is deploy-safe for its claimed scope and that later deliverables remain open.
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
- Say `done` only for the active bounded deliverable; never inflate it into whole-product completion.
- If no deploy/live proof exists, say so plainly.
- Keep the user explanation short and plain.
