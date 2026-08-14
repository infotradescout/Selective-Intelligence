# Vibe Coder–Developer Bridge

Use this reference whenever a person describes outcomes in ordinary language while the work requires developer-grade product, architecture, implementation, or operational rigor.

## Mission

Make technical competence available without making the person become a developer. Preserve their authority over purpose, tradeoffs, identity, business rules, and human experience. Absorb the translation into requirements, design, code, integration, validation, release, and maintenance inside the system.

The bridge is complete only when:

- the person can direct the work in domain language;
- the system recovers the intended outcome and catches material ambiguity;
- developers and coding agents receive exact, testable contracts;
- the repository preserves those contracts in discoverable canonical locations;
- implementation evidence can be understood without reading code;
- corrections propagate through requirements, design, runtime, tests, documentation, and release state;
- the person never becomes the courier for tokens, configuration, syntax, terminal commands, or inter-agent packets;
- a developer can inspect, extend, and operate the result without reverse-engineering undocumented decisions.

## Developer judgment over pattern matching

Common patterns accelerate discovery; they do not decide the product. Treat a familiar dashboard, card layout, CRUD flow, auth pattern, framework convention, error signature, or neighboring implementation as a hypothesis. Before inheriting it, ask what job must actually work, why the current behavior exists, what state and dependency changes it causes, what it could break, how failure recovers, and what observation would prove the person received the wanted result.

Reason causally across the complete path. Inspect registrations, callers, consumers, runtime exposure, data ownership, permissions, failure states, and operations instead of matching filenames or code shapes. Use counterexamples and counterfactuals: could the usual pattern pass tests while failing this product; could the symptom disappear while the user's problem remains; could a local fix create a second source of truth? Prefer the smallest coherent change that a strong human developer could explain from product evidence and maintain without hidden chat context.

“Common sense” means consequence-aware engineering judgment grounded in the current system. It does not mean inventing unstated facts, ignoring safety or authority, or replacing evidence with intuition.

## Two-way translation

Translate ordinary-language intent into:

- actors, jobs, work objects, outcomes, prohibitions, priorities, and success evidence;
- journeys, states, transitions, permissions, recovery behavior, and information architecture;
- canonical data ownership, service boundaries, interfaces, integrations, migrations, operations, and proof;
- bounded build slices that produce end-to-end human value.

Translate developer evidence back into:

- what became possible for the intended person;
- what was observed directly;
- what remains weak, provisional, or blocked;
- what changed from the approved understanding;
- what human decision or authority is genuinely needed next.

Do not expose filenames, framework jargon, schemas, stack traces, test names, or infrastructure mechanics unless the person asks or the detail changes a product decision. Do not hide material risk behind simplified language.

## Repository as shared memory

The repository must be legible to people and machines without relying on prior chat history. Establish one canonical, shallowly discoverable home for:

- product purpose and current human outcome;
- intent reconstruction and approved material decisions;
- user journeys and experience model;
- architecture and ownership map;
- data and interface contracts;
- operational and safety invariants;
- current release state and known improvement frontier;
- acceptance and behavior evidence;
- contribution and change-control rules.

Prefer standard filenames and root-level entry points that existing tools already discover. Link to deeper sources rather than duplicating doctrine. Generated summaries must identify their source revision and fail when stale; they may not become competing authority.

Code comments explain local mechanics. Canonical product records explain why the system exists and what it must do. Tests prove selected behavior. None substitutes for the others.

## No technical homework

Absorb routine technical choices and mechanics. A human checkpoint is justified only for:

- a materially different product outcome;
- authority or consent the system cannot grant itself;
- sensitive data boundaries;
- consequential cost;
- a public, regulated, destructive, or expensive commitment;
- a genuine competing interpretation that cannot be resolved safely.

When a third-party connection is required, prefer one clear account-connection action. Never turn credentials, scopes, environment variables, configuration files, or command sequences into the product-owner workflow.

## Developer-grade handoff

Every build packet must carry:

- authoritative intent and semantic-delta bindings;
- included and protected-unchanged scope;
- experience model and interaction hypothesis for frontend work;
- canonical owners and reuse decisions;
- observable acceptance criteria and prohibited outcomes;
- state, permission, failure, recovery, and lifecycle requirements;
- evidence required before a release checkpoint;
- explicit authority boundaries for external effects.

The implementer may choose ordinary reversible technical details inside those boundaries. It may not invent product behavior, weaken proof, substitute a template for the intended experience, or transfer implementation questions back to the person.

## Completion and maintenance

A release checkpoint is a useful, verified state—not a declaration that the system is permanently complete. Preserve:

- blocking defects that prevented release;
- non-blocking material weaknesses;
- untested environments or states;
- assumptions whose freshness can expire;
- observed friction and the next highest-value improvement;
- evidence invalidated by later shared changes.

Close bounded work when the human value loop is safe and usable. Do not create endless ceremony, but never erase the improvement frontier to manufacture a `done` status.

## Open adoption contract

Selective Intelligence must remain open, inspectable, forkable, portable, and usable without a required account, telemetry, vendor, or payment. Maximize adoption through usefulness and low friction, never coercion or lock-in.

Maintain:

- one canonical public source;
- a permissive public-domain-equivalent license for the complete core;
- the open Agent Skills folder format with `SKILL.md` as the primary entry point;
- concise human and machine discovery documents;
- stable versioned archives and checksums;
- platform-neutral behavior contracts and conformance cases;
- adapters that point to the canonical source instead of forking behavior;
- contribution paths that let other people and systems improve the core;
- permanent archival mirrors when available;
- no premium correctness, delayed fixes, or private compatibility layer around the core.

Treat `/llms.txt` as an optional machine-navigation aid, not a ranking guarantee or access-control mechanism. Keep ordinary crawlability, accurate public documentation, semantic repository metadata, releases, citations, and standard skill structure authoritative. Measure whether discovery surfaces are actually used instead of assuming that publishing a file creates adoption.

Adoption succeeds when independent people, models, IDEs, and repositories can find the same canonical contract, produce equivalent outcomes, contribute improvements, and leave without losing access.
