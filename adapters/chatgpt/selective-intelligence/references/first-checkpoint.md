# Checkpoints: intent locks and durable progress

Selective Intelligence uses two different checkpoint types. Confusing them creates either needless approval friction or lost work.

## 1. Intent and authority checkpoint

This checkpoint prevents expensive drift when meaning or consequence justifies a lock. It is not the default before every edit.

### When it fires

Use a checkpoint headed **What I understand you want** before consequential action only when:

- material ambiguity remains and plausible readings lead to meaningfully different outcomes;
- the request locks a whole product, system architecture, migration, or cross-system contract;
- the next action is public, irreversible, expensive, destructive, permission-changing, or exposes sensitive data; or
- the person explicitly requests an intent lock.

A clear correction, bounded repair, routine continuation, reversible local edit, or ordinary research task stays Lean.

### What it contains

Include only what prevents the identified drift:

- real-world outcome and intended person;
- non-negotiables and prohibitions;
- affected and excluded surfaces;
- observable proof;
- canonical owners to reuse;
- consequential authority reserved for the person.

Outside Platynum, use `APPROVE` or `CORRECT: <instruction>`. Approval unlocks only the described scope. A correction reopens affected meaning and invalidates dependent work and proof.

Do not require approval again for every harmless step under the same boundary.

## 2. Durable progress checkpoint

This checkpoint prevents loss. It is automatic, non-blocking, and does not ask the person to approve routine preservation of already-authorized work.

Create one:

- after each coherent completed slice;
- before beginning the next slice;
- before a long test, build, migration preparation, or external tool sequence;
- before changing model, agent, context, branch, or work surface;
- before likely timeout, capacity, or runtime boundaries;
- whenever one completed slice or five materially changed files remain uncommitted or only in working memory;
- immediately after a consequential external effect, with a receipt and a do-not-repeat note.

For repository work, commit only task-owned files. Preserve unrelated changes. When remote writing is available and the person has not required local-only work, push the checkpoint to the existing task branch. Do not push directly to protected branches merely to create a savepoint. A checkpoint push never authorizes merge, release, deployment, or production mutation.

When commit or push is unavailable, write a durable resume artifact inside the project and plainly identify what remains local.

### Required record

A durable progress checkpoint records:

- governing outcome and prohibitions;
- completed and verified work;
- changed but unverified work;
- repository, branch, base revision, and current revision or containing commit;
- saved files and their ownership;
- tests and evidence;
- external effects and receipts;
- actions that must not be repeated;
- next safe action;
- remaining authority requirement, if any.

A progress message, chat summary, or “still working” update without saved state is not a checkpoint.

## Resume rule

Resume from the checkpoint, actual source state, and external receipts. Never restart from persuasive conversation memory.

1. Inspect repository, branch, revision, and dirty changes.
2. Compare them with the checkpoint.
3. Verify external effects before retrying.
4. Continue from the first unproved transition.
5. Create a new checkpoint after the recovered slice.

Unknown external outcomes are never assumed safe to repeat.

## Enforcement boundary

Intent checkpoints protect meaning and authority. Progress checkpoints protect continuity. Neither replaces the other.

A runtime may enforce both, one, or neither. Do not claim a checkpoint stopped a third-party worker, committed files, or pushed a branch unless the actual wiring and evidence prove it.
