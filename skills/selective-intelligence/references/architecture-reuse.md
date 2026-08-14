# Architecture, Directorization, and Reuse

Use this reference before creating or reorganizing software. The repository must remember what it already knows. A feature that works but is scattered, duplicated, undiscoverable, or outside canonical boundaries remains a drift risk.

First create or refresh the generated project map in [project-index-and-reuse-gate.md](project-index-and-reuse-gate.md). A stale or missing index blocks new-code claims in a software project.

## Contents

- [Architecture discovery pass](#architecture-discovery-pass)
- [Canonical ownership map](#canonical-ownership-map)
- [Reuse decision](#reuse-decision)
- [New-code gate](#new-code-gate)
- [Directorization rules](#directorization-rules)
- [Practical reuse, not ritual DRY](#practical-reuse-not-ritual-dry)
- [Consolidation workflow](#consolidation-workflow)
- [Architecture validation](#architecture-validation)

## Architecture discovery pass

Before adding code, inspect:

- directory and package conventions;
- feature and domain boundaries;
- route and navigation registries;
- shared UI primitives and design tokens;
- hooks, services, clients, state stores, events, and jobs;
- schemas, validators, types, and generated contracts;
- utilities and cross-cutting infrastructure;
- tests, fixtures, factories, and story or preview systems;
- import aliases, public exports, and dependency rules;
- repository instructions that define ownership or placement.

Search by behavior and domain language, not only the proposed name. Similar responsibilities often hide behind different names.

## Canonical ownership map

For each requested responsibility, identify:

| Question | Required answer |
|---|---|
| Domain owner | Which feature or module owns this concept? |
| Canonical model | Where is its data shape and validation defined? |
| Canonical behavior | Which service, hook, controller, or state machine owns the rules? |
| Canonical interface | Which page, component, API, or event exposes it? |
| Shared primitives | Which stable cross-feature pieces already exist? |
| Registration | Which route, navigation, dependency, or export registry makes it reachable? |
| Verification | Where do its truthful tests belong? |

If multiple candidates claim ownership, treat that as architecture drift to resolve, not permission to add another candidate.

## Reuse decision

Assign every planned piece one disposition before implementation:

1. **Reuse as-is:** the canonical implementation already satisfies the responsibility.
2. **Extend canonical:** the owner is correct and needs an additional supported behavior.
3. **Extract shared:** repeated behavior is stable, truly equivalent, and needed by multiple owners.
4. **Consolidate or replace:** duplicate owners represent the same concept; migrate callers to one canonical implementation.
5. **Create new:** no existing owner fits and the responsibility is genuinely distinct.
6. **Remove:** obsolete, unreachable, superseded, or misleading code has no intentional compatibility role.

Do not create new code until the first five choices have been considered from repository evidence.

## New-code gate

A new feature, module, component, hook, service, schema, or utility is justified only when all are true:

- its responsibility is distinct and nameable in one sentence;
- no canonical implementation already owns that responsibility;
- extending an existing owner would create real coupling or violate its contract;
- its directory and dependency direction follow repository conventions;
- its public interface is smaller and clearer than direct scattered use;
- it is registered, reachable, consumed, and tested where applicable;
- it does not duplicate styling, validation, state, types, copy, or business rules.

“It was faster to write” and “the agent did not find the old one” are not valid reasons.

## Directorization rules

Use the repository's established convention when it is coherent. When the repository lacks one, organize by stable product responsibility rather than temporary task or screen names.

A feature-oriented directory may co-locate its page or entry surface, internal components, hooks, services, types, and tests. Keep genuinely shared primitives in the repository's shared layer. Do not move feature-specific code into shared merely because two files currently import it.

Require:

- one obvious home for each product concept;
- clear filenames based on responsibility;
- bounded public exports;
- internal helpers kept private to their owner;
- tests near the behavior or in the repository's canonical test location;
- route, navigation, service, and feature registration in canonical registries;
- dependencies flowing in the repository's intended direction;
- no catch-all files or directories that become dumping grounds.

Avoid:

- giant pages containing unrelated domain logic;
- generic `utils`, `helpers`, `common`, or `misc` additions without a precise owner;
- page-local copies of shared tokens, validation, formatting, or API logic;
- duplicate types that can disagree with canonical schemas;
- barrel exports that hide cycles or expose private internals when the repository avoids them;
- index files, registries, or manifest entries that are not updated with the new module;
- naming a replacement “new,” “v2,” “fixed,” or “final” instead of consolidating ownership.

## Practical reuse, not ritual DRY

Reuse equivalent responsibility, not superficial resemblance. Two components that look similar but enforce different domain rules may remain separate. Three copies of the same policy, validator, state transition, or token should usually have one canonical owner.

Extract only after identifying the stable shared contract. Do not create configurable mega-components that require many flags and encode unrelated workflows.

Prefer:

- shared low-level visual primitives with feature-owned composition;
- canonical domain services with explicit feature consumers;
- generated or shared types from authoritative schemas;
- small composable functions over copied blocks or omnipotent helpers;
- extension points already established by the repository.

## Consolidation workflow

When duplicates exist:

1. Determine actual intent and choose the canonical owner.
2. Compare callers, behavior, data assumptions, and tests.
3. Add missing required behavior to the canonical implementation.
4. Migrate consumers deliberately.
5. Preserve compatibility only where it is intentional and time-bounded.
6. Remove obsolete implementations, exports, flags, styles, tests, and documentation.
7. Re-search the repository for old names, imports, route paths, copy, and constants.
8. Verify the complete user path after consolidation.

Leaving the duplicate dormant is insufficient when it can be imported, routed, generated, or reactivated later.

## Architecture validation

After implementation, verify:

- every new file has an intentional owner and consumer;
- imports use canonical paths and do not introduce forbidden cycles;
- no equivalent module, component, schema, hook, or utility remains unexplained;
- route and registry exposure is complete;
- removed paths have no live callers or hidden generators;
- shared rules have one authoritative implementation;
- tests assert behavior through the intended boundaries;
- static analysis, build, and focused tests pass;
- repository search finds no stale alternative likely to resurface.

Report a new abstraction only when it materially affects the handoff. The user needs the coherent outcome, not an inventory of files.

## Council capability selection

Before dispatch, search installed skills, repository owners, project sources, and available tools by responsibility. Record each needed capability, candidate owner/reference, and one disposition: reuse, extend, extract, consolidate, create, or remove. A missing search record blocks a locked Worker Packet when new implementation is proposed.

In v0.2 this selection belongs in the Council case; do not create a competing persistent capability database. Agent spawning, browsing, filesystem access, connectors, and validation are capabilities to detect at runtime, not entitlements inferred from a plan name. Capability availability never grants action authority.
