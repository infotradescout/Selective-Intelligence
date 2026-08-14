# Platynum ↔ SI interrupt/approve wiring contract

Status: **Platynum wires clickable Approve/Correct to SI session-state transactions** (current checkpoint id + intent hash). Outside Platynum, clients use the text gate `APPROVE` / `CORRECT: <instruction>` — same transactions; never decorative controls.

## Product boundary

> **Platynum owns the clickable steering interface. SI owns the mandatory checkpoint, interrupt, correction, and execution-lock behavior everywhere.**

## Problem

Without an authoritative SI interrupt/approve transaction, Correct/Approve remains observation: generation, tool dispatch, and FS/Git mutations can continue under a rejected or unapproved interpretation.

## Claim scope (honest)

SI `interrupt` is an **atomic SI session-state interruption**:

- Sets `generationAuthority=false`, `mutationFrozen=true`, `executionLocked=true`, `correctionMode=true`
- Marks queued tasks cancelled; marks running/verifying/repairing cancelled or cancellation-requested in session state
- Taints completed effects bound to the rejected checkpoint
- Classifies correction as an intent operation (`RETRACT`, `REPLACE`, …)
- Emits a new proposed checkpoint; resume requires `approve` of that new checkpoint with matching intent hash

Until a product connection proves that model generation streams, tool dispatchers, and external workers actually honor those flags and stop, do **not** claim a full hard-stop of those runtimes.

## SI endpoints (authoritative)

```
POST /si/v1/sessions/{session_id}/interrupt
POST /si/v1/sessions/{session_id}/approve
```

CLI:

```
python build_engine.py interrupt --session <id> --correction "<text>" [--checkpoint <id>]
python build_engine.py approve --session <id> --checkpoint <id> --intent-hash <hash>
python build_engine.py text-gate --session <id> --response "APPROVE" --checkpoint <id> --intent-hash <hash>
python build_engine.py text-gate --session <id> --response "CORRECT: <instruction>"
```

### Approve

Must include the **current** checkpoint id and intent hash. Stale id or hash → fail closed.

### Correct / interrupt

1. Interrupt active run (session-state)
2. Cancel pending dispatch
3. Capture correction as `RETRACT` or `REPLACE` (operation-aware)
4. Create a new checkpoint
5. Continue only after that new checkpoint is approved

### Response (minimum for interrupt)

```json
{
  "interruptedCheckpointId": "cp-…",
  "newCheckpoint": { "checkpoint_id": "cp-…", "status": "proposed", "intent_hash": "…" },
  "operation": "RETRACT",
  "resumeRequiresApproval": true,
  "mutationFrozen": true,
  "generationAuthority": false
}
```

## Non-Platynum text gate

Do not render fake Approve/Correct controls. Require:

```text
APPROVE
CORRECT: <instruction>
```

Parsed by `scripts/text_gate.py`; applied via `build_engine text-gate` / `apply_text_gate`.

## Non-claims

- Calling SI interrupt is **session-state control**, not automatic proof of external model/tool/worker stop.
- Cross-model reliability remains unproven until matrix evals pass. Do not claim T2 from this wiring alone.
- No ops 5–7 expansion in this contract.
