# Product delivery acceptance

A successful component test is not a successful product delivery. Preserve the user's primary job, interaction mode, desired finish, prohibitions and existing canonical owner before implementation. Do not redefine an automatic product as a manual notebook when telemetry work is unfinished. Manual tools can be optional without becoming the main workflow. A small first delivery must close a real user loop, not merely expose internal records.

## Required acceptance packet

Use the canonical `scripts/quality_gate.py --delivery --contract <contract.json> --evidence <evidence.json> --artifact-root <evidence-directory>` at a product delivery boundary. This is agent/adapter work, not an instruction for the user to run a command. Preserve the complete product scope while selecting a bounded delivery. Requirements must state `automatic`, `interactive`, `manual`, or `optional_manual`, identify primary outcomes, and state whether proof must be synthetic, native or live. Do not reduce native/live requirements to synthetic to obtain a pass.

Bind evidence to the current contract hash, source revision, canonical code root, application entrypoint and data owner. Preserve unresolved user rejection as a blocker until its specific defects have been resolved and rechecked; an agent's confidence cannot substitute for the user's acceptance. Verify exactly one intended delivery target. Explicitly account for old installations and existing data before replacing or redirecting them. Never delete an old journal to make duplication disappear.

An automatic workflow must show its triggering change and resulting user-visible state without a manual-entry step. Prove startup, update, persistence and recovery in the required environment. Retain the distinction between synthetic replay, native observation and a live external event. An initial historical import is not a newly observed event. A working URL alone is not installation proof.

For primary user-facing work, require a rendered screen, actual interaction review and disposition of blocking usability findings. Review discoverability, data relevance, density, legibility, empty/error/loading/stale states and the amount of user effort. Test counts and attractive colors are not substitutes. Screenshots alone are insufficient. No numerical aesthetic score or model self-approval establishes acceptance.

## Enforcement and honest boundaries

`delivery_acceptance.py` validates the packet and referenced artifact bytes. The integrated quality CLI returns nonzero for missing, stale, wrong-mode or conflicting proof. Its strongest result is `ready_for_review`, never `user_accepted`. The original five-stage SI source gate remains separate and reports `productDelivery: not_evaluated`.

These checks cannot authenticate fabricated reports, infer a correct product definition from an arbitrary string, intercept ungoverned tool calls, or force an external client to adopt them. An adapter must invoke the gate before promoting product-delivery state. Source publication is not runtime installation. Complete adapter/distribution regeneration, full repository validation and an installed-client forward test before claiming system-wide enforcement. Keep this work unmerged while those gates are outstanding.

## Repeated discovery failures

The `admit_discovery` helper caps equivalent searches for one unresolved question and target, rejects searching a known path, and requires polling an existing search handle. The caller must persist its returned ledger. Query rewording and context reset must retain the same question identity. It is not yet a universal interceptor of connector calls. A safety denial is never made retryable by this helper.

## Regression fixture

The test suite models a failed automatic companion: two competing app targets, manual input substituted for automatic capture, many passing component tests, a screenshot without interaction review, an unstarted collector, old evidence after a correction, and unresolved dissatisfaction. Every case must remain blocked. The fixtures are synthetic validator tests, not evidence that a real game or product passed acceptance.
