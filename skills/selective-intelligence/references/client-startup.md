# Client startup and saved-work continuity

`scripts/client_startup.py` is a read-only lifecycle adapter over the canonical progress checkpoint format. It does not replace `build_engine.py`, approve tasks, dispatch a model, or certify completion.

It accepts a bounded JSON event on standard input with `hook_event_name`, `session_id`, and absolute `cwd`. Supported events are `SessionStart`, `UserPromptSubmit`, and `Stop`. Startup and prompt events return `hookSpecificOutput.additionalContext`; Stop records observations only. Identical prompt context is suppressed when an observation directory is supplied.

Lookup uses the exact current Git root. An optional user-owned `--registry` may select a checkpoint explicitly for that root. Otherwise the adapter reuses the existing worktree-private progress checkpoint before the repository's tracked checkpoint. It never scans other repositories or full chat transcripts. No command in a checkpoint is executed.

The adapter checks the current revision, branch, bounded saved-file hashes, checkpoint schema, optional root binding, path containment, symlinks, and potential secret content. Missing, changed or stale evidence is reported as such, without forwarding its next action as current. Windows drive paths and the current WSL distribution are supported when running under WSL; other distributions must not be silently mapped to the current one.

An optional `--state-root` receives per-session observation receipts. Those receipts cannot change engine task states or manufacture verification results. Keep them private. The adapter reads no account credentials and performs no network calls.

For supported Codex clients, configure command hooks through the documented user or project `hooks.json`. Use a real installed interpreter and immutable runtime path, not a Windows Store alias. Review and trust each exact definition using the client's supported hook-review interface. Do not edit trust hashes, classify user hooks as enterprise-managed, disable approvals, or bypass hook trust. Installing the file is not proof that a client loaded or trusted it.

Register SessionStart for startup, resume, clear and compact. UserPromptSubmit updates context after saved work changes; Stop preserves an observation, not an inferred handoff. The working agent must still save meaningful progress through the existing checkpoint helper and retain current user intent and permission boundaries.

Acceptance separates: source tests; direct fresh-process adapter invocation; client discovery/trust; actual automatic delivery before a fresh task; and meaningful task execution. Only the last two establish client adoption for the tested client. Other clients, current sessions already running, and normal ChatGPT conversations need their own supported entrypoints and evidence.

Official client contract: https://developers.openai.com/codex/hooks
