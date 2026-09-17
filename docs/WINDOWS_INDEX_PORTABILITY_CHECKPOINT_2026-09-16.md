# SI Windows index portability — 2026-09-16

Objective: Continue the existing Windows runtime repair without replacing the installed skill or weakening authorization, evidence, source-reuse, or filesystem protections.
Base branch/commit: codex/si-windows-byte-preservation-20260916 at c5f3ecf60dbe33a20643a5c8198bf2738c43b740; draft PR #54 stacked on #51.
Current branch/commit: same branch, containing commit. Resolve PR #54 for the latest exact execution evidence.

Verified completed work:
- Reproduced missed CRLF/LF duplicate implementations and failure when the Git executable is absent. Added six platform-independent index regressions; all pass on native Windows.
- Preserve raw file bytes, SHA-256 and exact-file groups. Add a separately labeled CRLF-to-LF equivalent-implementation group. New copies still fail PI001 before target writes.
- A common duplicate-implementation finding preserves inherited-debt semantics. A new regression first failed when merely changing an existing duplicate's line endings, then passed after correction. Eighteen final index/reuse tests pass.
- Missing Git falls back to filesystem inventory with unknown revision/cleanliness and explicit unavailable probe status. Permission denials and timeouts still propagate.
- Native correction/approval/write/verify/reload and interruption tests pass within the 36-test focused run before the final inherited-debt refinement.
- Fix mocked-writer and no-op fixtures to create their declared exact bytes. A new counterexample requires an actual newline-only change to remain a real write, not a false no-op.
- Permission preservation compares the actual pre-write native mode; POSIX still requires 0640. No ACL, operating-system privilege, or symlink policy is changed.
- Regenerate the canonical 59-file ChatGPT adapter, including the earlier exact-byte writer repair. This is source packaging, not client installation.

Files changed: canonical project_index.py; three existing transaction/worker/reuse test files; new test_project_index_portability.py; generated adapter runtime files/metadata; this checkpoint. No product source or global installed skill is changed.
Tests/evidence already run: six index regressions (baseline 1 failure/2 errors; repaired all pass); 36 focused native Windows tests pass; inherited-debt regression failed before and passes after; final 18 index/reuse tests pass; git diff --check passes.
Changed but unverified work: final full Windows/Linux suite, quality/release acceptance, and installed-client operation. The original intermediate Windows quality command ran and failed unit_tests/release_integrity; other three controls passed. Do not promote that to a passing gate.
Tests/evidence invalidated by later changes: final duplicate-finding wording and additional inherited-debt test require final suite evidence. Final actual results must be saved in PR #54 and local project-execution receipts without overwriting prior failed logs.
Known blockers/risks: Windows symlink privileges were unavailable in prior runs; no elevation, synthetic pass, or skip-to-green is authorized. Release-doctor control identity also remains open pending fresh evidence.
External side effects/retry safety: isolated source worktree only; generated adapter in that worktree; ordinary draft publication is the intended next step. No installation, main merge, deployment, customer action, secret access or production modification.
Next exact action: finish the original full Windows test invocation, execute final tests on native Ubuntu with matching source bytes, inspect failed gate evidence, and retain exact commit/results. Install only after actual acceptance, not because these focused tests pass.
Actions not to repeat: broad SI audit, replacing installed SI with an unaccepted candidate, weakening staged-byte checks, erasing inherited duplicate debt, claiming all projects are governed from global instruction files alone.

Scout boundary: its request-flow inspection/write calls were blocked before execution in this continuation. They were not retried through alternative routes. Scout remains at 05b7ad1c with its earlier 210-case core proof; missing request-specific native flows remain open.

Packaging correction: The complete 343-test Windows run found the new test missing from release_files, alongside the three prior symlink-privilege errors and one existing skip. Added only tests/test_project_index_portability.py to that reviewed file list; runtime_files and validation rules remain unchanged. Regenerated the existing adapter. All 27 package/index/reuse checks then passed. Full final-candidate results are recorded in PR #54 and the local project-execution receipt.
