# UI/UX and Output Standards

Use this reference for every user-facing surface and every request where the output medium affects usability.

Apply [product-design-intelligence.md](product-design-intelligence.md) first. This reference implements and verifies a selected experience model; it cannot rescue an interface whose underlying product form is wrong.

## Contents

- [UI/UX is product behavior](#uiux-is-product-behavior)
- [Design from the user journey](#design-from-the-user-journey)
- [Lock design constraints across iterations](#lock-design-constraints-across-iterations)
- [Inspect before designing](#inspect-before-designing)
- [Prevent generic AI UI](#prevent-generic-ai-ui)
- [Interaction requirements](#interaction-requirements)
- [Copy, control, and destination contract](#copy-control-and-destination-contract)
- [Visual hierarchy gate](#visual-hierarchy-gate)
- [Rendered QA is mandatory](#rendered-qa-is-mandatory)
- [Public-surface completeness](#public-surface-completeness)
- [Choose the correct output medium](#choose-the-correct-output-medium)
- [Marketing collateral rule](#marketing-collateral-rule)
- [PDF-first document gate](#pdf-first-document-gate)
- [UI/UX verdicts](#uiux-verdicts)
- [Agent response economy](#agent-response-economy)

## UI/UX is product behavior

Do not treat design as colors and spacing applied after implementation. UI/UX determines whether the intended user can understand the product, find the right action, complete the job, recover from failure, and trust what happened.

Before implementation, establish:

- primary user and immediate job;
- first-screen comprehension target;
- primary and secondary actions;
- information hierarchy and progressive disclosure;
- required states and transitions;
- brand and product doctrine;
- device, accessibility, and input constraints;
- realistic content volume and edge cases;
- observable evidence that the experience works.

## Design from the user journey

Map the real sequence:

`entry → orientation → decision → primary action → system response → confirmation → recovery or next action`

Every screen must have a clear role in that sequence. Do not create screens merely because a data model has fields or a framework makes pages easy.

For first-time visitors, test whether the page communicates what the product is, who it serves, what it enables, why it is different, and what to do next. A visually attractive page that omits major product capabilities is incomplete.

## Lock design constraints across iterations

Maintain an internal constraint ledger for iterative design work. Include:

- required spatial relationships and ordering;
- elements that must remain side by side, stacked, centered, sticky, visible, or hidden;
- exact real assets and forbidden substitutions;
- primary and secondary CTA labels, destinations, colors, and ownership;
- required content, modules, and product capabilities;
- accepted prior corrections and rejected patterns;
- breakpoint-specific behavior;
- brand, tone, and non-negotiable visual rules.

Before each revision, compare the proposed change with every locked constraint. Do not improve one dimension by silently regressing a previously corrected one. When constraints conflict, resolve actual intent instead of guessing.

## Inspect before designing

Inventory and reuse the canonical design system:

- typography, spacing, color, elevation, border, radius, and motion tokens;
- layouts, shells, grids, navigation, forms, cards, dialogs, and feedback primitives;
- responsive breakpoints and platform conventions;
- accessibility helpers and interaction patterns;
- brand-specific components and prohibited patterns;
- existing screens that have been explicitly accepted.

Do not introduce raw one-off values, duplicate primitives, or a new visual language unless actual intent requires a deliberate system change. If the current system is incomplete, extend it canonically and migrate consumers.

## Prevent generic AI UI

Do not default to:

- oversized empty heroes;
- every section inside a card;
- nested cards and panels without hierarchy;
- equal visual weight for every action;
- decorative gradients, glows, glass effects, or blobs without brand purpose;
- excessive pills, badges, icons, and status labels;
- generic dashboards, fake metrics, or meaningless charts;
- technical system language exposed to ordinary users;
- placeholder testimonials, counts, ratings, reviews, logos, or activity;
- feature grids that substitute enumeration for product understanding;
- mobile layouts produced only by stacking desktop blocks.

These patterns are not universally forbidden. They require a product reason rather than AI habit.

Treat a complaint about landing pages, generic dashboards, cards, or long vertical scrolling as a possible rejection of the interaction model. Do not respond only with tighter spacing, new colors, or rearranged sections. Return to the Experience Model and compare job-specific alternatives.

## Interaction requirements

- Make the primary action obvious without suppressing necessary context.
- Use plain, domain-correct language.
- Keep controls visually consistent with their consequence and ownership.
- Preserve entered work across recoverable failures when safe.
- Distinguish loading, empty, offline, permission, validation, failure, partial-success, and success states.
- Never render sentinel, mock, local-only, or unknown data as real user truth.
- Make destructive and irreversible actions explicit.
- Keep keyboard, focus, labeling, contrast, target size, and screen-reader behavior functional.
- Verify back, close, cancel, retry, deep-link, and session-resume behavior where relevant.

## Copy, control, and destination contract

Every interactive control must agree across four layers:

`visible label → visual affordance → actual destination/action → resulting state`

A button labeled “Open Scout” must open the intended Scout surface. A dropdown must look expandable, expose the expected choices, and maintain accessible state. A destructive action must not look like ordinary navigation. A link must not promise a capability that the destination lacks.

Verify analytics, tests, selectors, redirects, navigation, and help copy against the same current contract. Renaming the visible label alone is incomplete when legacy routes or tests remain authoritative.

## Visual hierarchy gate

At each target breakpoint, confirm:

1. The user understands the page's purpose within seconds.
2. The eye reaches the primary action in the intended order.
3. Important differences are expressed through hierarchy, not just more copy.
4. Content density matches the job and real data volume.
5. Secondary details remain available without competing with the main path.
6. Repeated modules are consistent and reusable.
7. Empty space serves comprehension rather than masking missing substance.

## Rendered QA is mandatory

Do not approve UI/UX from source code, component names, or passing logic tests alone.

Render the actual surface with representative content and inspect:

- desktop and relevant mobile or tablet breakpoints;
- long names, missing media, long copy, empty collections, and dense collections;
- loading, error, offline, unauthorized, and success states;
- menus, dialogs, dropdowns, sticky elements, and overlays;
- clipping, overflow, wrapping, tap targets, scroll behavior, and safe areas;
- visual token adoption and brand consistency;
- the full primary user journey, not isolated screenshots.

Inspect the actual routed surface rather than a component preview when route, shell, authentication, data loading, or navigation can change the experience. Use real or representative production-shaped content, never convenient fixtures that conceal layout or state failures.

## Public-surface completeness

For landing pages, profiles, About pages, shared links, and other public surfaces, also verify:

- title, description, social preview, canonical URL, and crawler-visible content;
- the correct logged-out shell and entry path;
- public assets resolve and are sized appropriately;
- static public files do not retain stale contact, brand, legal, or product information;
- performance-sensitive imagery is compressed and responsive;
- deep links and shared URLs resolve to the same intended experience as in-app navigation.

A correct SPA component is not sufficient if crawlers, logged-out visitors, or shared links receive a different shell or stale content.

Use screenshots as validation evidence. A screenshot is not a substitute for the functioning surface.

## Choose the correct output medium

Default by intended use:

| Intended outcome | Primary deliverable |
|---|---|
| Interactive application, website, or interface | Working code and runnable preview |
| Proposal, one-pager, plan, printable guide, report, spec, or designed document | Render-verified PDF, with editable source when useful |
| Flyer, poster, brochure, sell sheet, handout, media kit, promotional sheet, or text-bearing marketing collateral | Render-verified PDF master; export channel-specific images from it when required |
| Photo, illustration, texture, scene, or raster artwork | Image |
| Social graphic with important text, pricing, dates, offers, or layout precision | Verified layout/PDF master, then platform-sized image export |
| Precise diagram or quantitative chart | Structured diagram/chart source or vector-capable document, not generated raster art |
| UI implementation proof | Screenshots plus functional validation |

Do not flatten a document or marketing layout into an image when the user needs readable text, accurate spelling, pricing, dates, contact information, multiple pages, printing, search, selection, accessibility, or predictable layout. Do not create a PDF when the actual product is an interactive experience.

## Marketing collateral rule

Treat image generation as an artwork source, not a precision layout engine. For flyers and marketing products:

1. Build the information hierarchy and exact copy first.
2. Compose the piece with real text, vector shapes, grids, and controlled image placement.
3. Use generated or retrieved imagery only as a supporting asset when appropriate.
4. Create a PDF master and render it for visual inspection.
5. Verify spelling, numbers, dates, prices, URLs, contact details, offers, disclaimers, and calls to action.
6. Export PNG or JPEG variants from the approved master when social, email, advertising, or web channels require raster files.

Do not ask an image model to render the entire text-bearing flyer and then repair its spelling or geometry through repeated generation.

## PDF-first document gate

For fixed-layout and marketing deliverables:

- use real text and vector shapes where practical;
- establish page size, margins, grid, typography, hierarchy, and pagination;
- preserve selectable text and working links;
- avoid screenshots of text as document content;
- render every page to images for visual inspection;
- check clipping, overflow, blank pages, contrast, spacing, and page breaks;
- deliver the PDF as the primary artifact after verification.

An attractive source file is not proof. The rendered PDF is the product to inspect.

## UI/UX verdicts

- **Aligned and verified:** actual intent is authoritative, the full journey works, and rendered QA passed.
- **Functionally correct, visually unverified:** behavior passed but rendered inspection is incomplete.
- **Visually polished, product-incomplete:** presentation is strong but required capabilities or states are missing.
- **Not aligned:** hierarchy, language, behavior, or output medium contradicts actual intent.

Never collapse these verdicts into “looks good.”

These are release-checkpoint verdicts, not permanent completion claims. Preserve material weaknesses, untested states, observed friction, and the next highest-value improvement after every handoff.

## Agent response economy

The chat response is also output. Spend tokens on building, not narration.

- Lead with the result and its proof. When reporting work, state repo, branch, what changed, and pass or fail; omit a restated plan or a walkthrough of steps already visible in the transcript.
- Reference artifacts by path or link instead of pasting their contents. Quote only the lines that carry the point.
- Do not repeat the request back, re-explain a decision the user already made, or narrate options you decided against.
- Keep user-facing wording plain for non-developer readers; move engineering detail into model- and harness-facing files.
- Brevity never suppresses a required disclosure. Still surface material assumptions, blockers, unverified states, and any action that needs authority — compactly.

This is economy, not omission: a shorter response that hides a blocker or an unproven claim fails the truth standard, not passes the output one.
