# Main Systems Control Plane

This file is the durable cross-project entry point for the owner's primary systems. It exists so new Work/Codex sessions resume active work instead of rediscovering every repository.

## Scope

Primary systems:
- TradeScout — `infotradescout/tradescoutAI`
- MealScout — `infotradescout/MealScout`
- Sway — `infotradescout/sway.tips`
- Selective Intelligence — `infotradescout/Selective-Intelligence`

Essential TradeScout-owned lanes:
- JW Stone / stone inventory, receiving, pricing/cart/access
- TradeScout design tools, with cabinets and countertops as the current design priority
- Exchange and HomeID when they are dependencies of the active TradeScout release lane

Side repositories are not part of the default main-system execution loop merely because they embed SI. Work them only when the owner explicitly promotes them or a main-system dependency requires them.

## Resume rule

On every new main-system Work/Codex session:
1. Read the target repo `AGENTS.md` and current SI rules.
2. Inspect the newest relevant open PR(s) and their current head/base before broad repository search.
3. Treat those PR bodies, exact revisions, evidence receipts, and linked handoffs as the starting breakpoint.
4. Continue from the first unproved transition. Do not repeat already-proved audits, builds, browser matrices, or broad tests unless later changes invalidate them.
5. Keep independent lanes moving concurrently when owners/files/contracts do not overlap.
6. Before interruption or capacity exhaustion, update the existing PR/handoff with exact current head, completed work, remaining proof, actions not to repeat, and one next safe action.

## Current breakpoints — 2026-09-13

### TradeScout
Primary integration lane: PR #662 `platform/weekly-release-proof-20260913`.
- Integrates Core UI/HomeID (#658), Infinity consumer reuse (#657), Exchange batch import (#659), and dependency security (#661).
- Current published head recorded in the PR: `3c0bd84ac0d35f7aec7bece4186346db260b01fd`.
- Remaining work: finish exact combined platform + JW proof and reconcile receipts; do not restart the four input audits.

JW Stone stacked lane: PR #660 `jw-stone/receiving-release-20260913`.
- Current combined candidate recorded in the PR: `5c61359613261738069f8ae032c7bacc99bede0d`.
- Remaining work: complete/verify combined receiving + Core + Exchange proof, then preserve release ordering and owner authorization boundary.
- Older PR #655 is provenance for employee receiving/access/cart work; do not restart from #655 when #660 contains the integrated candidate.

Design tools:
- Cabinets and countertops remain essential TradeScout product lanes.
- No current open PR was found by title for cabinet/countertop work at this checkpoint; next execution should locate their canonical current owners inside TradeScout before creating any new implementation and must not perform a platform-wide audit to do so.

### MealScout
Audit-repair lane: PR #378 `repair/mealscout-audit-20260913`.
- Repairs reviewed failures from the 274-feature audit.
- Remaining work: browser preview/acceptance and remaining feature acceptance; do not rerun the 274-feature discovery audit from zero.

Production-recovery lane: PR #377 `codex/mealscout-release-recovery-20260913`, stacked on #376.
- Current published head recorded in the PR: `ff36ea83ba003f3bab427d0db4f668a02f54eed7`.
- Remaining work: complete the hosted full proof, including the unchanged 170-case browser matrix/native fixtures/final clean-source receipt, then reconcile with #378 where scopes overlap.
- #376 and #375 are provenance/input lanes; resume from #377 for the integrated recovery unless a specific regression requires inspecting the source PR.

### Sway
Current completion lane: PR #244 `implement/sway-collaborator-revisions-20260913`, stacked on #243.
- Current head recorded in the PR: `7789c2b579c39e3a2f8ee055de12df5ee79b66e5`.
- Remaining work: finish the collaborator revision acceptance gaps and required external/native proofs without redoing the prior feature audit.

Base completion/recovery lane: PR #243 `implement/sway-completion-20260913`.
- Current head recorded in the PR: `6d37f43686087713e445d520a7e9f60346bd961b`.
- Its full contract gate currently fails at native Chromium startup; treat that as the breakpoint rather than rerunning unrelated source audits.
- PR #242 is already a proved integrated input for Sources/account boundaries/dependency security and should be reused as evidence unless invalidated by later changes.

### Selective Intelligence
Canonical resume-first hard gate merged in PR #52.
- SI must optimize verified implementation per unit of compute.
- Main-system continuity and current breakpoints belong here; avoid propagating project-specific state into unrelated repositories.

## Parallel execution policy

Keep these lanes moving at once when capacity exists:
- TradeScout platform integration
- JW Stone receiving/inventory
- TradeScout cabinet/countertop design tools
- MealScout audit repairs
- MealScout production recovery
- Sway completion/collaborator revisions
- SI continuity/efficiency fixes only when they directly improve execution of the above

Do not spend a main-system capacity slot on unrelated SI-enabled repositories while one of these lanes has executable work.
