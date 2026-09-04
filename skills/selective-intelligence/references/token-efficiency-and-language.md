# Token efficiency and human language

Token efficiency governs the whole run because wasted context causes drift, repeated work, correction, and lost progress. It never means shrinking the wanted outcome or dropping proof.

## Startup budget

- Start Lean work with the master skill only: zero references, zero role packets, and one active context.
- Load at most one reference before the first useful action unless a recorded safety or Council trigger requires more.
- Pass only the outcome, prohibitions, relevant evidence, authority boundary, artifact, and proof question to another worker.
- Prefer deterministic search, validators, indexes, targeted ranges, and exact owners over broad ingestion.

## Whole-run governor

Every added source, file, worker, search, or check must do at least one of these:

1. change the next decision;
2. reduce a material risk;
3. prove or disprove an acceptance condition.

If it does none, do not spend context on it.

For large repositories, inspect no more than 12 text files or 64 KB in one batch. Use targeted ranges for any larger file. Exclude binaries, generated output, dependencies, secrets, and unrelated history. After each batch, update one compact evidence ledger, state what decision changed, and select the smallest next batch.

Use one owner per bounded question. Do not send the same repository slice or question to overlapping workers. A second worker needs a different proof question.

Before a second persistent repository batch, open the usage ledger in the bundled checkpoint helper. Record the question, owner, number of files, byte count, decision/risk/proof impact, and one short result. The helper rejects:

- more than 12 files;
- more than 64 KB;
- a second owner for the same question;
- a fourth search or inspection batch without a recorded decision.

After three batches, choose one:

- act on the supported decision;
- narrow the unresolved question;
- create a durable progress checkpoint and resume from saved state;
- stop with the strongest supported result and exact unknown.

Do not keep searching merely because more sources exist.

## Evidence ledger

Keep only:

- governing outcome and correction;
- confirmed facts;
- unknowns that can change the result;
- canonical owners;
- selected evidence and why it matters;
- completed proof;
- next decision.

Record a source once. Reference the ledger instead of copying full source content into plans, reviewers, and handoffs.

## Context-pressure triggers

Checkpoint before continuing when:

- history no longer changes decisions;
- one coherent completed slice or five materially changed files remain only in memory or uncommitted;
- a long test, build, migration preparation, handoff, context change, or likely runtime limit is next;
- the same facts are being reread or re-explained;
- a timeout, capacity limit, or tool boundary may interrupt the run.

Resume from the saved artifact and current source state. Do not reconstruct the task from conversation memory.

## Spend in this order

1. Recover intent.
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
- Were batches held to 12 files and 64 KB, then consolidated?
- Did the usage ledger stop duplicate ownership and a fourth undecided batch?
- Was progress saved before context pressure or a long operation?
- Was the existing owner reused before new code was proposed?
- Does every user-facing sentence carry a result, decision, proof, limit, or required action?
