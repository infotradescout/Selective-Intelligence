# Selective Intelligence Sub-Skills

Selective Intelligence keeps each Council role in a small reference module so one agent can do one bounded job at a time.

Each role reference is built in plain, easy-to-understand language:
- one short goal
- few clear steps
- one simple output packet

Use these in order for full-stack work:

1. `si-intake` — gets the user goal in one simple question and starts the run.
2. `si-planner` — writes the intent lock and lane plan.
3. `si-worker` — does the hands-on build or repo work.
4. `si-queue-manager` — keeps the active work on the right queue item and only interrupts on real mismatch.
5. `si-objector` — checks the work for missed steps and weak claims.
6. `si-aligner` — fixes drift and decides if it is actually aligned.
7. `si-verifier` — runs a final user-facing handoff and checks.

The parent `selective-intelligence` skill runs the full flow and may hand each phase to a separate agent/context after reading the matching `ROLE.md` reference.
