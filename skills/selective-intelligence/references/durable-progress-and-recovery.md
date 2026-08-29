# Durable progress and recovery

Use this reference whenever work can outlive one response, tool run, context window, worker, or local workspace. The purpose is simple: completed work must become recoverable before the next risky step begins.

## The anti-loss invariant

Never hold more than:

- one coherent completed slice; or
- five materially changed files

without a durable checkpoint.

A coherent slice is a bounded outcome that can be explained, inspected, and resumed independently, such as a repaired route, completed component state, migration draft, research decision, document section, or verified artifact.

## Checkpoint order

For authorized repository work:

1. Inspect the current branch, revision, dirty changes, and unrelated user work.
2. Select only files owned by the current slice.
3. Run the fastest relevant validation that can catch a destructive save.
4. Write the progress record.
5. Commit the selected files and record on the existing task branch.
6. Push that branch when remote writing is available and local-only work was not required.
7. Record the push result, proof, and next safe action.
8. Only then begin a long command, new slice, handoff, or context change.

Never stage all repository changes blindly. Never discard or rewrite unrelated work to make a clean checkpoint.

## Safe branch policy

Routine preservation belongs on an existing non-protected task branch. It does not belong directly on `main`, `master`, `trunk`, `production`, `prod`, or a release branch unless the person explicitly authorized that exact target.

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
- outcome and active correction;
- scope and prohibitions;
- completed and verified work;
- changed but unverified work;
- repository, branch, base revision, and containing commit or local revision;
- task-owned files included;
- tests, rendered proof, and known failures;
- external effects with receipts;
- actions not to repeat;
- current blockers;
- next safe action;
- exact remaining authority step.

Do not store secrets, raw private prompts, hidden reasoning, customer data that is not needed for continuity, or unsupported claims.

## Before long operations

Create the checkpoint before:

- dependency installation or a large build;
- broad test suites;
- migration generation or rehearsal;
- image processing, crawling, or bulk import;
- deployment preparation;
- cross-repository integration;
- changing models, agents, contexts, branches, or worktrees;
- any operation whose failure or timeout could erase the ability to explain or recover current work.

A command finishing successfully does not preserve earlier uncommitted work. Save first.

## External effects

After sending, publishing, purchasing, deploying, migrating, changing access, or triggering another provider, record:

- exact target;
- action;
- observed result;
- receipt, revision, identifier, or URL;
- whether retry is safe, unsafe, or unknown;
- compensation or rollback path.

An unknown result is not a failure and not a success. Inspect actual state before retrying.

## Resume protocol

On resume:

1. Load the latest durable checkpoint.
2. Inspect actual repository and external state.
3. Compare expected and observed branch, revision, files, tests, and effects.
4. Classify the checkpoint as current, interrupted, superseded, conflicting, or reconciled.
5. Resume from the first unproved state transition.
6. Revalidate proof invalidated by shared changes.
7. Save a new checkpoint after the recovered slice.

Do not restart the original plan from step one. Do not repeat external actions merely because a new worker cannot see their result.

## Fallback when Git is unavailable

Write the record and completed artifact to a durable project location. Include file hashes or exact saved paths when possible. State that the work is saved locally but not remotely protected.

Do not tell the person that work is backed up, pushed, or recoverable from another device unless the evidence proves it.

## User-facing update

A checkpoint update should be short:

**Saved checkpoint:** what is complete, where it is preserved, what proof passed, and what starts next.

Do not dump internal logs or the full record into the conversation. The durable artifact carries the details.
