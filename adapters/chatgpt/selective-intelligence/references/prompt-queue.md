# Prompt Queue and Pre-PR Cache

When prompts are coming fast, users and agents can lose context across branch/PR flips.
This protocol prevents that.

## Why this exists

- keep every user request that has not been fully shaped into a PR slice
- keep a durable order of intended work
- avoid mixed-context drift when branches, models, or threads change
- make it easy to remove items only when they are fully fleshed

## Cache location

Use one local queue file:

- `.selective-intelligence/prompt-queue.jsonl`

It is line-delimited JSON with small, safe records.

## Item states

- `queued` — user request is captured and waiting
- `in_progress` — being turned into a plan/slice
- `fleshed` — scope is implemented/closed and safe to remove
- `discarded` — intentionally dropped

## Queue rule (simple)

1. **Before** a prompt gets reworked in a new context, add it to the queue.
2. Assign or claim one queued item per bounded slice.
3. Do work and create the matching branch/PR.
4. Once it is completed and merged/recorded, remove it from queue.
5. Keep only open items (`queued` + `in_progress`) visible for resume.

## Queue manager role (for agent-capable runs)

When queueing is active and prompts are coming fast, a `si-queue-manager` pass can run during
worker lanes:

- It reads `.selective-intelligence/prompt-queue-snapshot.json`.
- It runs `python scripts/prompt_queue.py check ... --enforce-sequential`.
- It returns `continue` only when there is no true mismatch.
- It returns `interrupt` only when ownership, branch, status, or sequence mismatches are real.

This means the work stops only on drift (wrong queue item, wrong owner, wrong branch, or skipped
sequence), not on normal local progress.

For non-developer users, this is an internal operator lane. The person should never run these commands.
The AI should perform queue checks and keep the request continuity automatically.

## Suggested integration with SI runs

- On `JumpStart` or intake, enqueue the raw request.
- On branch-per-slice work, bind queue id into the branch name or branch note.
- When PR is ready, mark queue item as `fleshed`.
- Then run `prune` (or remove by id) so only real open work stays.

## Continuity rule (for non-developers)

A request is never "gone" just because threads moved.
It only disappears from the queue when a human-approved slice is done.

## Command examples (operator mode only)

- Add a request:
  `python scripts/prompt_queue.py enqueue --prompt "fix login" --source user-chat --branch feat/mobile`

- See open items:
  `python scripts/prompt_queue.py list --status queued --status in_progress`

- Mark item as done:
  `python scripts/prompt_queue.py set-status --queue-id <id> --status fleshed`

- Remove completed rows:
  `python scripts/prompt_queue.py remove --queue-id <id>`

- Clean only closed items:
  `python scripts/prompt_queue.py prune`
