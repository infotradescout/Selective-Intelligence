# Step-1 intent-control runtime status

Governing diagnosis (authoritative): SI doctrine was ahead of runtime. “Documented is not enforced” described SI itself. Failure occurs **before** PolicyGuard / tests / verification matter when the model acts on an unapproved interpretation.

**Root cause:** SI did not own interpretation authority.

**Required sequence:** reject-before-wrong-work (not post-hoc feedback metrics).

A prior golden-packet benchmark worked because a pre-specified packet already did Step-1. Ordinary live conversation did not get equivalent enforcement. PolicyGuard pass ≠ Step-1 fidelity.

## Platynum surface vs SI authority

| Layer | Status |
| --- | --- |
| Platynum T0 | Shipped |
| Platynum live steering UI / gate (PR #2) | **Merged** — clickable “What I understand you want” + Approve/Correct |
| Platynum T2 Intelligence/Checkpoint product loop | Pending |
| SI Step-1 P0 (ops 1–4) | **Enforced in Python runtime** (includes defect patches + approve intent-hash fail-closed + text gate) |
| Platynum Approve/Correct → SI transactions | **Wired** — Approve sends current id + intent hash; Correct → interrupt → RETRACT/REPLACE → new checkpoint → re-approve; stale fails closed; external stop unproven |
| Non-Platynum text gate | **Enforced** — `APPROVE` / `CORRECT: …` via `scripts/text_gate.py` (same transactions; no decorative controls) |
| Cross-model / cross-client equivalence | **Unproven** — do not claim REVIEW_PASS, T2, or Tier-4 |

**Product boundary:** Platynum owns clickable steering. SI owns checkpoint/interrupt/correction/execution-lock everywhere. Outside Platynum, never render decorative Approve/Correct — use the text gate only.

## Screenshot failure class (acceptance)

User narrow instruction → agent invents halt → user: “i didnt say halt did i? nope.” → agent invents freeze/resume → user corrects → agent narrates unrelated background work.

That is Step-1 intent-control failure. Keyword parsers that miss `didnt`≠`don't`, `nope`≠standalone `no`, and treat `halt` as product intent fall through incorrectly. A model `structured_override` that labels the same utterance as `ADD`/`MODIFY` must still yield `RETRACT`.

**Now enforced (deterministic):** that utterance classifies as `RETRACT` of the halt interpretation, not product intent; interrupt updates SI session state (cancel queued; cancel/request-cancel running/verifying/repairing; taint rejected-checkpoint effects; require a new approved checkpoint before resume). Claim scope: **atomic SI session-state interruption** — not proven external model/tool/worker stop until product connection demonstrates it.

## Enforced now (P0 ops 1–4)

1. **Intent operations** — `ADD | MODIFY | REPLACE | RETRACT | SUPERSEDE | ROLLBACK` in `scripts/intent_contract.py`. Repudiations are not unioned into refinements. Text-derived `RETRACT` survives conflicting model overrides.
2. **First checkpoint = execution lock** — `start` emits a **proposed** checkpoint; plan/discovery/worker/FS/Git/external work stays locked until `approve`. Workspace `mkdir` is deferred until approval.
3. **Bind all work** — tasks, worker packets, artifacts, verifications, and action receipts carry `authorized_checkpoint_id` + `authorized_intent_hash`. Stale hash / unapproved / superseded / correction-mode / non-current checkpoint → fail closed. Session `generationAuthority` is true only while an approved current checkpoint authorizes work. Approve accepts optional `expected_intent_hash` and fails closed on mismatch.
4. **Atomic interrupt (session-state)** — `build_engine interrupt|correct|text-gate` and `checkpoint.interrupt`: set session `generationAuthority` false, prevent SI-gated tool dispatch, cancel queued tasks, cancel/request-cancel running+verifying+repairing in session state, freeze mutations, taint completed effects from the rejected checkpoint, capture correction, emit new proposed checkpoint, show removed/retained/changed, resume only after approve. Dislike/reject/approve require `currentCheckpointId`.

## Still doctrine / scaffolded (ops 5–7)

5. **Semantic corrections** — deterministic retract/replace paths exist; richer conversational ops (“criticism not new task”, “preserve objective, remove process directive”) are scaffolded in evals as `pending_semantic` and must not be claimed complete.
6. **External stop proof** — Platynum calls SI interrupt/approve (session-state). External model/tool/worker stop remains unproven. See [platynum-interrupt-wiring.md](platynum-interrupt-wiring.md).
7. **Behavioral matrix / cross-client evals** — cases added; pass requires equivalent authoritative intent **and** equivalent outcome across clients. Not claimed here.

## Honest taxonomy

- **Platynum surface:** T0 + live-steering UI with executable Approve/Correct wired to SI
- **Intelligence/checkpoint product:** pre-T2 — do **not** claim T2
- **SI:** partial Tier-1 controls; **Step-1 P0 ops 1–4 qualified in SI runtime tests**; interrupt is session-state-enforced; text gate for non-Platynum; cross-model equivalence **unproven**
- **Observational / unproven:** external model generation streams, tool dispatchers, and workers actually stopping
- **Session-state-enforced in SI (+ product call):** generationAuthority, execution lock, deferred mkdir, binding hashes, cancel/taint flags, current-checkpoint-only decisions + intent-hash on approve; Platynum → `/api/model/interrupt` and `/api/model/approve`
