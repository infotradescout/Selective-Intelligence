# Project Index and Reuse Gate

Use this reference in every software project before adding or moving directories, modules, components, hooks, services, schemas, helpers, functions, or UI primitives.

## One project memory

Maintain one generated file at `.selective-intelligence/project-index.json`. It records:

- source directories and file counts;
- source files and content digests;
- top-level and exported functions, hooks, classes, types, and components;
- candidate UI primitives and every raw button, input, select, textarea, and form use;
- exact duplicate files and exported symbols with competing owners;
- explicitly declared canonical directories, UI primitives, and shared symbols;
- reuse decisions that must survive refreshes.

Do not create separate function logs, component catalogs, directory maps, and AI notes that can disagree. The generated index is the machine navigation surface; authoritative product and architecture decisions stay in the existing specification system or Start Pack and are referenced from the index rather than copied.

## Automatic lifecycle

On activation in a repository:

1. run `python scripts/project_index.py refresh --root <project>` using the installed Selective Intelligence package;
2. inspect errors, warnings, primitive candidates, symbol collisions, and the intended owner before proposing new code;
3. assign the planned work one disposition: reuse, extend, extract, consolidate, create, or remove;
4. record canonical owners and the reuse decision in the project index or existing authoritative architecture record;
5. refresh after implementation;
6. run `python scripts/project_index.py doctor --root <project>` and block handoff if the index is stale or a canonical declaration points to a missing owner.

`Start Pack init` creates the index automatically. Existing repositories do not need to understand the command; the AI running Selective Intelligence owns setup and refresh.

## Creation gate

Creating new code is allowed only when the refreshed index and repository inspection show that:

- no existing owner already has the responsibility;
- extension or consolidation would be the wrong product boundary;
- the destination directory is canonical or deliberately established;
- the public interface is distinct and consumed;
- no styling, validation, state, type, copy, or business rule is being duplicated;
- relevant callers, registrations, tests, and old alternatives are reconciled.

An index warning is a search lead, not automatic proof of a defect. An exact duplicate file, competing exported owner, stale index, or missing canonical owner is a blocking architecture fact until resolved or explicitly justified in the governing project record.

## UI proliferation rule

Before adding another button, card, field, form, dialog, table, or layout wrapper:

- find the canonical primitive and its consumers;
- extend it when the responsibility is the same;
- keep feature composition with the feature owner;
- consolidate near-copy primitives and migrate callers;
- use raw elements only when the design system intentionally owns them or the project records a bounded exception.

The goal is not one mega-component. It is one obvious owner per stable responsibility and no accidental collection of dozens of slightly different variants.

## Evidence boundary

The scanner is dependency-free and intentionally conservative. It inventories JavaScript, TypeScript, JSX, TSX, and Python source using syntax-aware Python parsing and bounded source patterns. It can prove freshness, exact duplication, and visible ownership collisions; it cannot decide product equivalence from names alone. The AI must inspect behavior and consumers before consolidation.
