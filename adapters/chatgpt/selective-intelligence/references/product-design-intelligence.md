# Product Design Intelligence

Use this reference before creating or substantially changing any interface, website, application, workflow, profile, dashboard, tool, or frontend. It governs product judgment before component implementation and rendered QA.

## Governing posture

Assume the first interface idea is probably conventional, incomplete, and biased toward whatever the framework makes easiest. A clean render, fashionable styling, component reuse, or passing accessibility scan does not prove that the experience is useful.

The job is not to decorate requirements. The job is to choose and prove the interaction model that best helps the intended human accomplish the real task.

No interface is ever “A1,” perfect, or permanently finished. It may be the strongest verified release checkpoint supported by current evidence. Every release retains an improvement frontier grounded in observed friction, missing states, weak comprehension, or untested conditions.

## Diagnose the product experience before drawing screens

Build an internal Experience Model from the Intent Reconstruction Record:

| Element | Design question |
|---|---|
| Entry condition | What does the person know, possess, or need when they arrive? |
| Desired change | What should be easier, faster, safer, clearer, or newly possible when they leave? |
| Work object | What real thing are they viewing, configuring, comparing, buying, operating, or deciding about? |
| Critical decision | What choice must the interface help them make? |
| Primary action | What action moves the real job forward? |
| Information need | What must be visible before that action becomes trustworthy? |
| Interaction frequency | Is this a one-time decision, repeated operation, monitoring task, exploration, or collaboration? |
| State model | What changes over time, who owns it, and what must persist? |
| Risk and recovery | What can go wrong and how does the person recover without losing work? |
| Device reality | Where, how, and under what physical conditions will the interface be used? |
| Success evidence | What observed behavior proves the experience helps? |

Do not infer a page list from the database schema. Infer the minimum coherent experience from the human journey and work object.

## Choose the interaction model deliberately

Before styling, select the product form that fits the job. Examples include:

- focused task flow;
- visual configurator or designer;
- search and compare workspace;
- command center or operations console;
- guided decision tool;
- map, timeline, board, canvas, table, catalog, or detail workspace;
- collaborative review surface;
- profile or public trust surface;
- concise landing page only when orientation and conversion are actually the job.

Never default to a marketing landing page for a request that needs a working tool. Never default to a dashboard merely because several metrics exist. Never default to a long vertical document merely because responsive stacking is easy.

When the job contains multiple connected actions, design the smallest integrated workspace that keeps context intact. Use tabs, split views, drawers, steps, canvases, inspectors, comparison trays, sticky action regions, or route-level subviews only when they reduce memory burden and preserve orientation.

## Generate experience alternatives, not theme variants

For material new UI work, form at least three meaningfully different experience hypotheses internally. They must differ in information architecture or interaction model, not merely colors, card shapes, or hero copy.

For each hypothesis evaluate:

- time to first useful result;
- number and difficulty of decisions;
- context switching and memory burden;
- fit for real content volume;
- ability to compare, revise, resume, and recover;
- mobile and desktop viability;
- trust, proof, and error visibility;
- brand distinctiveness without novelty theater;
- technical feasibility using the canonical system;
- risk of turning into a brochure, generic dashboard, or card collection.

Select or combine the strongest hypothesis against the actual job. Preserve rejected hypotheses and why they failed only in internal design evidence; do not make the person choose among incomplete technical concepts unless the choice is genuinely a product commitment.

## Information architecture and density

Design hierarchy around decisions and actions:

1. orient the person;
2. expose the work object;
3. show the information needed for the next decision;
4. make the primary action unmistakable;
5. keep secondary detail nearby without competing;
6. confirm consequences and preserve a path forward.

Density must match the job. Operational and comparison work often benefits from compact, information-rich layouts. Exploration may need visual breathing room. Empty space is not quality when it hides missing capability. More sections are not completeness when they force a long scroll through disconnected blocks.

Treat mobile as a different interaction environment, not a desktop column collapse. Decide what becomes persistent, summarized, paged, swiped, tabbed, collapsed, or deferred while preserving the core job.

## Frontend substance gate

The first delivery of an interactive product must be an end-to-end usable slice, not a styled shell. Require:

- the real primary workflow is reachable from the actual route and shell;
- every visible primary control performs its promised action;
- realistic or production-shaped data exercises the layout;
- loading, empty, error, denied, partial, success, undo, retry, and resume states exist where the workflow can produce them;
- navigation, back, cancel, close, deep-link, refresh, and session behavior preserve orientation and work;
- forms explain requirements in domain language and retain safe input across recoverable failures;
- results connect to the next human action instead of ending at a decorative confirmation;
- public and authenticated surfaces expose the correct truth to the correct audience;
- the design system is extended canonically rather than bypassed with one-off values;
- accessibility and keyboard behavior work in the actual routed experience.

No button may be included as theater. Hide unfinished actions or finish them. Do not use fake metrics, unsupported counts, placeholder testimonials, invented urgency, or sample prices presented as fact.

## Anti-template challenge

Before accepting a design, try to prove it is generic. Challenge:

- Could the logo and nouns be replaced and the screen belong to any unrelated startup?
- Did a hero, feature grid, card wall, dashboard, or sidebar appear without a job-specific reason?
- Are there many equal-weight actions because prioritization was avoided?
- Is explanatory copy compensating for an unclear interaction?
- Is a long scroll substituting for navigation or progressive disclosure?
- Are pills, badges, gradients, glass, icons, and rounded panels carrying style but no meaning?
- Did mobile become a single exhausting column?
- Does the screen showcase the system instead of helping the person do the work?
- Are internal states, partner mechanics, implementation terms, or back-office language exposed?
- Would the person still need a phone call or separate tool to finish the job the screen claims to handle?

Any “yes” is a design defect to resolve or explicitly justify.

## Render-use-observe loop

Source code is not design evidence. For every material surface:

1. run the actual application;
2. enter through the intended route and role;
3. use representative dense, sparse, long, missing, delayed, and failed data;
4. complete the primary journey using real controls;
5. inspect desktop and relevant mobile/tablet sizes;
6. capture screenshots at decision points and state transitions;
7. test backtracking, interruption, correction, recovery, and resume;
8. record friction and compare it with the intended Experience Model;
9. revise the causal design decision, not just the visible symptom;
10. rerun affected journeys and breakpoints.

Use browser automation for repeatable mechanics and direct visual inspection for hierarchy, density, clarity, and character. Neither alone is sufficient.

## Design evidence scorecard

Judge each release checkpoint on observed evidence:

| Dimension | Passing question |
|---|---|
| Comprehension | Can the intended person explain the purpose and next action quickly? |
| Utility | Can they complete the real job without a hidden manual workaround? |
| Interaction cost | Are steps, choices, and context switches proportionate to the job? |
| Information scent | Can they predict where controls and destinations lead? |
| Hierarchy | Does visual emphasis match consequence and priority? |
| Density | Is the right amount of real information available at each decision? |
| State integrity | Are loading, failure, permission, partial, and success states truthful? |
| Recovery | Can mistakes and interruptions be repaired without needless loss? |
| Responsiveness | Does each target device preserve the job rather than merely fit the screen? |
| Accessibility | Can people use the experience with keyboard, screen reader, zoom, and reduced motion? |
| Distinctiveness | Does the experience express this product's actual advantage rather than generic styling? |
| Trust | Are consequences, evidence, uncertainty, pricing, ownership, and status honest? |

Do not collapse these dimensions into “looks good.” A release cannot outrank its weakest dimension that blocks the primary job.

## Design Objector

For material UI work, use a fresh-context Product Design Objector after the first usable implementation. Give it the Intent Reconstruction Record, Experience Model, routed preview, representative tasks, and screenshots. Do not give it the implementer's persuasive narrative.

Require it to find:

- a competing interaction model that may fit better;
- the strongest evidence the current design misunderstands the job;
- hidden manual work or dead ends;
- generic-template signals;
- hierarchy, density, responsive, accessibility, and state failures;
- one realistic user journey that the design makes unnecessarily difficult.

The Aligner disposes findings against observed behavior and authoritative intent. Popular taste, novelty, and model consensus are not proof.

## Continuous improvement without endless blocking

Use these verdicts:

- **Release-blocked:** the primary job, truth, safety, or essential recovery path fails.
- **Usable checkpoint:** the end-to-end job works and blocking defects are absent, but material weaknesses remain recorded.
- **Strong checkpoint:** the job works across representative states and devices, design evidence is strong, and remaining issues are non-blocking.
- **Observed regression:** a previously proven dimension failed after change.

Never use `perfect`, `finished forever`, `A1`, or an equivalent absolute verdict. Close the bounded release when it is safe and useful; preserve the evidence-backed improvement frontier for the next cycle. Do not manufacture busywork or prevent delivery merely because optional polish remains.

Read [ui-ux-and-output.md](ui-ux-and-output.md) for implementation and rendered-output standards after the product-design decision is established.
