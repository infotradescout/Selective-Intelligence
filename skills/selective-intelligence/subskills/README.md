# Selective Intelligence Sub-Skills

Selective Intelligence includes small, separately runnable role modules. Orchestrator, Worker/Builder, and Objector responsibilities apply to every work turn. For material project work, use separate bounded contexts when available; a same-context pass is degraded, not independent.

Each sub-skill is built in plain, easy-to-understand language:
- one short goal
- few clear steps
- one simple output packet

Use the core roles first; select extra roles only when their Council trigger applies:

- Challenge the candidate intent before `si-worker` mutates, then have `si-objector` review its result and proof.
- Add `si-intake` or `si-planner` only for unresolved competing interpretations or a whole-system lock.
- Add `si-aligner` only when findings conflict.
- Add `si-queue-manager` only when a real queue exists.
- Use a distinct context for material intent and result review when available.

The parent `selective-intelligence` skill carries the full flow. Role labels alone never prove independent review.
