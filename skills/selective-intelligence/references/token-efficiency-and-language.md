# Token efficiency and human language

Token efficiency is the first operating priority because wasted context causes drift, repeated work, and more correction. It governs the whole run. It never means shrinking the wanted outcome or dropping proof.

## Startup budget

- Keep the canonical `SKILL.md` under 1,500 words and 12,000 characters.
- Start Lean work with the master skill only: zero references, zero role packets, and one active context.
- Load at most one reference before the first useful action unless a recorded safety or Council trigger requires more.
- Pass only the outcome, prohibitions, relevant evidence, authority boundary, artifact, and proof question to another worker.
- Prefer deterministic search, validators, indexes, and targeted ranges over broad ingestion.

## Whole-run governor

Every added source, file, worker, search, or check must do at least one of these:

1. change the next decision;
2. reduce a material risk;
3. prove or disprove an acceptance condition.

If it does none, do not spend context on it.

For large repositories, inspect no more than 12 text files or 250 KB in one batch. Exclude binaries, generated output, dependencies, secrets, and unrelated histories. After each batch, consolidate the evidence ledger, state what decision changed, and select the smallest next batch.

Use one owner per bounded question. Do not send the same repository slice or question to overlapping agents. A second worker needs a distinct proof question, not a second copy of the task.

After three search or inspection batches, choose one:

- act on the supported decision;
- narrow the unresolved question;
- create a durable progress checkpoint and resume in a fresh context;
- stop with the strongest supported result and exact unknown.

Do not continue gathering repeated evidence merely because more sources exist.

## Evidence ledger

Keep a compact working ledger with:

- governing outcome and correction;
- confirmed facts;
- open unknowns that can change the result;
- canonical owners;
- selected evidence and why it matters;
- completed proof;
- next decision.

Record a source once. Cite or reference it from the ledger rather than copying its full contents into plans, reviewers, and handoffs.

## Context pressure

Treat these as checkpoint triggers:

- the conversation or worker is carrying history that no longer changes decisions;
- more than one coherent completed slice is still only in memory or an uncommitted workspace;
- more than five materially changed files lack a durable checkpoint;
- a long test, build, migration preparation, context change, or agent handoff is next;
- the same facts are being reread or re-explained;
- a timeout, capacity limit, or tool boundary may interrupt the run.

Checkpoint first. Resume from the saved artifact and current source state instead of reconstructing the task from conversation memory.

## Spend in this order

1. Recover intent before generating.
2. Inspect the named target.
3. Reuse the canonical owner.
4. Build the smallest complete authorized slice.
5. Save the slice.
6. Verify the result.
7. Report result, proof, limitation, and next authority step.

## Write like a person

Use concrete nouns and verbs. Say what changed, what works, what failed, and what remains unknown. Delete generic narration, repeated plans, encouragement, doctrine speeches, and sentences that could fit any project.

Technical terms are useful only when they identify evidence or a real constraint. Never hide a missing result behind polished language.

## Completion check

- Did every context expense change a decision, reduce risk, or prove acceptance?
- Did the run stay single-context unless a real escalation trigger was recorded?
- Were batches bounded and consolidated?
- Were duplicate searches, overlapping workers, and repeated history avoided?
- Was progress saved before context pressure or a long operation?
- Was an existing owner reused before new code was proposed?
- Does every user-facing sentence carry a result, decision, proof, limit, or required action?
