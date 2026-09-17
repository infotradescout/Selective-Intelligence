# Windows byte-preservation checkpoint — 2026-09-16

Objective: Make authorized SI staged writes preserve the exact UTF-8 bytes supplied by the worker on Windows without weakening staged-byte verification.
Base branch/commit: codex/si-harness-runtime at a810deebca2a36decf1bb6238aa5cbc7f2d9f269 (PR #51).
Current branch/commit: codex/si-windows-byte-preservation-20260916, containing commit. This is a bounded source repair, not installation or release approval.

Verified completed work:
- The real Windows guarded-write adapter translated LF to CRLF while its evidence described the original LF bytes. The strict staged-byte guard correctly rejected the mismatch.
- A native Windows regression first failed on the prior adapter, then passed after setting newline="" on the existing write_text call. Mixed LF/CRLF, Unicode, actual bytes, byte count and SHA-256 receipt are checked.
- The same regression passed under Ubuntu Python. Authorization and the strict staging comparison are unchanged. No alternate write adapter or weaker equality check was added.

Files changed: skills/selective-intelligence/scripts/policy_guard.py; skills/selective-intelligence/tests/test_policy_guard_command_resolution.py; this checkpoint.
Tests/evidence already run: Native Windows and Ubuntu `python -B -m unittest test_policy_guard_command_resolution.PolicyAdapterPortabilityTests` from the tests directory: one test passed on each platform. Windows prior-source regression failed as expected. Canonical project index was refreshed before this edit with zero reported errors/warnings.

Windows full-suite observation, NOT a passing gate:
- Prior LF checkout: 334 tests; failures=9, errors=22, skipped=1.
- After this repair: 335 tests; failures=8, errors=5, skipped=1.
- The reduction does not establish Windows support. Remaining observations include unavailable symlink privileges, process-launch portability, POSIX-mode assumptions and newline-sensitive duplicate/no-op fixture expectations. Their root causes and corrections remain separate work.
- The earlier CRLF checkout also failed release doctor because its deterministic control identity did not match recorded evidence. No receipt or release manifest was edited to hide this failure.

Changed but unverified work: Full Windows acceptance, full post-change Linux quality gate, release/adapter regeneration and real-client dispatch. The installed user-level SI directory was NOT replaced. Its own older quality gate passed independently; that does not certify this repaired candidate.
Tests/evidence invalidated by later changes: Rerun the named native regression for changes to guarded_write_text or its test. Prior PR #51 Linux proof is historical and does not prove this new source or Windows installation.
Known blockers/risks: Full Windows suite remains failing as recorded. No operating-system security setting, privilege, tool restriction, command allowlist, file-ownership rule or release guard was changed.
External side effects and retry safety: Isolated source worktree and nonproduction draft publication only. No product checkout, project-owned .selective-intelligence data, global installed skill, provider credentials, customer records or production service changed by this repair.
Next exact action: Fix the remaining Windows command and newline/fixture portability issues with narrow reproductions, retain real symlink/permission limitations, rerun the original complete quality command, and verify an actual save/resume/execute client session before installing broadly.
Actions that must NOT be repeated: Broad SI rediscovery, replacing the working installed skill with this unverified candidate, bypassing the byte comparison, marking skipped/failed checks passed, or claiming all-project runtime governance from documentation alone.
