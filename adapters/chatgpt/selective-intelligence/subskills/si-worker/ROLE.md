---
name: si-worker
description: Use for the bounded Worker/Builder responsibility on every Selective Intelligence work turn; use a separate context for material project work when available.
---

# SI Sub-Skill: Worker

## What this skill does (plain language)
It executes one bounded task after the Orchestrator reconstructs intent and the Objector double-checks it. For material work, the Objector challenges a plausible wrong interpretation and consequence before Worker dispatch. A formal Council packet applies only when that lane is selected.

## Inputs
- Orchestrator's bounded task, authoritative user intent, and resolved pre-work challenge
- Current formal Worker Packet when an SI engine or Council owns execution
- Active repository files, issue state, and existing implementation

## Existing execution owner

Follow [the corrected execution contract](../../references/model-neutral-execution.md#product-identity-and-corrected-execution). Keep an existing Start Pack project lock or execution session as the owner; do not initialize a parallel one.

When the engine owns the session, obtain its current worker packet before generating work. Read the complete `task`, including `metadata` requirements, operations, dependencies, acceptance references and invalidation conditions, plus the selected context. The title alone is not the task. Missing, blocked or over-budget material requires reconciliation, not guessed requirements or silent truncation.

For this engine-owned path, return the format specified by the packet's `requiredOutput`: the unchanged top-level `sessionId`, `taskId`, `authorized_checkpoint_id`, and `authorized_intent_hash`, actual `producer` information, and `files` mapping safe relative paths to complete UTF-8 text. The engine applies those files and runs verification. An operation description is not permission to execute it directly or bypass that owner. The general summary below accompanies the result; it does not replace the required result format.

Do not relabel old work, invent missing bindings, or redirect a result to another task. After a correction, discard dependent stale work and obtain the fresh packet. Report external-worker shutdown only with actual stop evidence. Returning a valid packet does not itself prove correct behavior or installed-client adoption.

## Steps
1. Read the authoritative intent, resolved challenge, bounded task, and current code. Do not mutate while a material interpretation remains unresolved.
2. Make only the edits needed for this slice.
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
- Match every changed behavior to the governing intent and any formal Intent Lock.
- Never claim tests passed without proof.
- Avoid asking the user to do technical steps that can be done in code.
- Explain any technical point in plain, non-developer language.
