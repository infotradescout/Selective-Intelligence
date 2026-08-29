# Durable progress and recovery

Use this whenever work can outlive one response, tool run, context window, worker, or workspace. Completed work must become recoverable before the next risky step begins.

## Anti-loss invariant

Never hold more than one coherent completed slice or five materially changed files without a durable checkpoint.

A coherent slice is a bounded outcome that can be explained, inspected, and resumed independently, such as a repaired route, completed component state, migration draft, research decision, document section, or verified artifact.

## Checkpoint order

For authorized repository work:

1. Inspect the current branch, revision, dirty changes, and unrelated work.
2. Select only files owned by the current slice.
3. Run the fastest relevant validation that can catch a destructive save.
4. Write the progress record.
5. Commit the selected files and record on the existing task branch.
6. Push when remote writing is available and local-only work was not required.
7. Verify the remote branch contains the checkpoint revision.
8. Record proof and the next safe action.
9. Only then begin a long command, new slice, handoff, or context change.

Never stage all changes blindly. Never discard or rewrite unrelated work to create a clean checkpoint.

## Bundled work guard

Use `scripts/progress_checkpoint.py` when it can run.

Its progress commands create a bounded recovery record, selectively commit task-owned files, push the existing task branch, verify the remote revision, preserve unrelated changes, and reject routine checkpoint commits to protected branches.

Its usage commands open a private evidence ledger before a second persistent repository batch. They reject more than 12 files or 64 KB in one batch, overlapping ownership of the same question, and a fourth search or inspection batch without an `act`, `narrow`, `checkpoint`, or `stop` decision.

When the helper cannot run, reproduce the same behavior with available repository tools. Do not continue after a checkpoint or usage-stop trigger until the required state is observed.

The helper keeps one tracked `latest.json` recovery record. Git history provides the checkpoint timeline, preventing one new tracked file per save. Local operation and usage receipts remain in the repository-private Git area and do not dirty the working tree.

## Safe branch policy

Routine preservation belongs on an existing non-protected task branch. It does not belong directly on `main`, `master`, `trunk`, `production`, `prod`, or release branches without exact authorization.

A progress push is preservation, not publication. It does not authorize:

- opening or merging a pull request;
- changing the default branch;
- releasing a package;
- deploying;
- running a production migration;
- changing credentials, access, billing, DNS, or provider settings.

## Minimum progress record

Store a concise, privacy-safe record containing:

- checkpoint identifier and time;
- outcome, active correction, scope, and prohibitions;
- completed and verified work;
- changed but unverified work;
- repository-relative location, branch, base revision, and containing commit;
- task-owned files included;
- tests, rendered proof, and known failures;
- external effects with receipts;
- actions not to repeat;
- current blockers;
- next safe action;
- exact remaining authority step.

Do not store secrets, absolute local paths, unrelated file names, raw private prompts, hidden reasoning, or unnecessary customer data.

## Before long operations

Checkpoint before:

- dependency installation or a large build;
- broad test suites;
- migration generation or rehearsal;
- image processing, crawling, or bulk import;
- deployment preparation;
- cross-repository integration;
- changing models, workers, contexts, branches, or worktrees;
- any operation whose failure could erase the ability to explain or recover current work.

A successful command does not preserve earlier uncommitted work. Save first.

## External effects

After sending, publishing, purchasing, deploying, migrating, changing access, or triggering another provider, record the exact target, action, observed result, receipt or revision, retry safety, and rollback path.

An unknown result is neither failure nor success. Inspect actual state before retrying.

## Resume protocol

1. Load the latest durable checkpoint.
2. Inspect actual repository and external state.
3. Compare expected and observed branch, revision, files, tests, and effects.
4. Classify the checkpoint as current, interrupted, superseded, conflicting, or reconciled.
5. Resume from the first unproved state transition.
6. Revalidate proof invalidated by shared changes.
7. Save a new checkpoint after the recovered slice.

Do not restart the original plan from step one. Do not repeat external actions because a new worker cannot see their result.

## Fallback without Git

Write the record and completed artifact to a durable project location. Include hashes or exact saved paths when possible. State that the work is saved locally but not remotely protected.

Do not claim work is backed up, pushed, or recoverable from another device unless evidence proves it.

## User-facing update

Keep it short:

**Saved checkpoint:** what is complete, where it is preserved, what proof passed, and what starts next.

A progress message without saved state is not a checkpoint.
