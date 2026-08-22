---
name: si-queue-manager
description: Use only when a selected Selective Intelligence Council has a real multi-item queue whose ownership or sequence needs checking.
---

# SI Sub-Skill: Queue Manager

## What this skill does (plain language)
It checks if the current lane is still the right one before letting work keep going.
Use this skill only when the orchestration has snapshot access and can run a short pre-check. If not, the worker
runs the same queue snapshot check before each continuation step.

## Inputs
- Current worker snapshot (`prompt-queue-snapshot.json`)
- `prompt-queue.jsonl` queue file
- Optional branch lock (`branch=<name>`)

## Steps
1. Read the snapshot and find that queue item in the queue.
2. Confirm:
   - owner is expected
   - branch is expected
   - status matches expected status
   - item is still in the right sequence for this branch (no early skipping).
3. If every check passes, return **continue**.
4. If checks fail on a real mismatch, return **interrupt** with one sentence reason and do not let the worker change branch or continue.

## Output
Return:
- `decision` (`continue` / `interrupt` / `complete`)
- `reason` (if interrupt)
- `next_skill` (`si-worker` for continue, `si-planner` for interrupt)
- `resume_packet` (small note for handoff)

## Non-negotiable rules
- Only interrupt on real mismatch, not on normal next-step progress.
- Keep all output in short plain language.
- Do not invent extra claims or status checks not in the queue record.
