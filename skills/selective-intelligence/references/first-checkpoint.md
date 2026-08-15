# First Checkpoint

The first response to any build-shaped request is a locked, full-scope intent checkpoint —
recovered from minimal input — not code, not an unbounded promise, and not a permission request.
The checkpoint preserves the complete discovered product while selecting one information-complete,
end-to-end first deliverable that fits the current execution window. Discovery can be broad;
execution must be bounded. The skill's readiness is measured by how few correction rounds a user
needs to reach a correct checkpoint; the target is zero.

## Contents

- [When it fires](#when-it-fires)
- [The checkpoint artifact](#the-checkpoint-artifact)
- [Information sufficiency before execution](#information-sufficiency-before-execution)
- [Enforcement](#enforcement)
- [Failure classes this gate refuses](#failure-classes-this-gate-refuses)
- [The measure](#the-measure)
- [Relationship to the modes](#relationship-to-the-modes)

## When it fires

Any request to build, create, complete, design, ship, integrate, or "finish" a product,
feature, system, or campaign — anything beyond a Tier 0 scratch throwaway (see
[friction-ladder.md](friction-ladder.md)). If it is unclear whether the work is Tier 0, it is
not; fire the checkpoint.

## The checkpoint artifact

Emit all of the following from the minimal input, inferring aggressively from the seed, existing
artifacts, and evidence, and naming each material assumption. Do not ask the user for what can be
recovered.

1. **Recovered full intent** — the largest truthful outcome the seed supports, not the literal
   minimal ask. Treat the prompt as a seed, never as the product-definition size.
2. **Whole-product decomposition** — the complete system as bounded slices (tiers), each with
   inputs, outputs, an owner, and its proof. No slice is dropped for being hard or large. Mark one
   first deliverable active and preserve the rest as ordered later deliverables.
3. **Canonical reuse map** — for each slice, what already exists to reuse or extend
   (repositories, patterns, prior art, this skill's own machinery). Rebuilding what exists is
   forbidden: reuse → extend → extract → only then add.
4. **Build sequence** — the slices ordered by dependency, marking which are parallelizable
   (council fan-out) and which are serial.
5. **Proof plan** — the observable success criteria for each slice and for the whole outcome;
   what "done" means, gated on evidence, never on activity or agreement.
6. **Authority split** — the genuine human decisions (irreversible actions, consequential cost,
   sensitive-data boundaries, brand, external mutation) separated from everything the model
   infers and executes without asking.
7. **Constraint reconciliation** — check the stated constraints against each other and flag any
   contradiction *before* building. Constraints often conflict silently: "non-developer" and
   "no backend" cannot both hold for one-click auth; "runs on the device" and "heavy build"
   cannot both hold without offload. Surface the conflict and resolve it in the checkpoint, not
   mid-build after committing to the wrong architecture.
8. **Human-layer activation steps** — enumerate every action *only the human can take* to make
   the outcome live (obtain a key, register an OAuth app, deploy, approve, connect a source), up
   front. These are discovered at checkpoint time, never mid-build. Everything else is the AI's
   to build; the human-layer list is the exact, minimal set of steps left for the person.
9. **Execution boundary and target** — define the active deliverable's complete user loop, proof,
   dependencies, and fit to the current run. Choose the execution environment from the product's
   operational requirements and established repository workflow, not tool convenience. Apply
   [execution-bounding-and-target-selection.md](execution-bounding-and-target-selection.md).

Stamp the checkpoint with a UTC timestamp and carry it forward (see
[time-awareness.md](time-awareness.md)).

## Information sufficiency before execution

No part of the active deliverable starts until every input needed to perform that deliverable is
in hand and the whole-product definition is sufficient to prevent an incompatible foundation.

- **Recover first.** Fill the information by inference from the seed, the repository, connected
  evidence, and established constraints before considering a question.
- **Resolve genuine unknowns in one consolidated, up-front pass** — only the few answers that
  would materially change the active deliverable, authority, sensitive-data boundary,
  consequential cost, or an irreversible foundation choice. Ask them together, once, in plain
  language, with recommended defaults.
- **Record future unknowns without blocking independent value.** A later deliverable's unknown
  input does not block the active slice unless the slice depends on it or would make the future
  choice expensive or irreversible. Resolve it before that later deliverable's Definition Lock.
- **Never trickle-ask inside the active deliverable.** Starting it on partial information is drift.

## Enforcement

- No application code and no permission-per-step before the checkpoint exists, the active
  deliverable is information-complete, and its execution contract passes validation.
- Present the checkpoint, then execute under the authority split — confirming only the genuine
  decisions, once, not each step.
- Erasing discovered product scope is drift. Sequencing it into bounded deliverables is required.
  "Smallest viable release" preserves the full outcome while completing one useful loop at a time.
- A deadline or context window is not authority to erase scope, skip proof, or inflate a partial
  result. It is evidence used to choose a smaller complete active loop.
- If the delivered result is not what the person wanted, Step 1 failed and reopens. Do not
  downgrade the wanted outcome to match a free-tier quota, unavailable tool, external company
  boundary, implementation shortcut, or technically successful substitute. Record the
  constraint, recover the missed meaning or path, and correct it. Only an explicit user-approved
  amendment made after the difference is clear can change the target.

## Failure classes this gate refuses

Mined from real correction sessions; each is a named guard:

- **scope-reduction-as-completion** — trimming the deliverable to fit one thread or one day and
  calling the whole product done. Bounded sequencing is not this failure.
- **discovery-to-execution explosion** — attempting to research, architect, build, integrate, and
  verify every discovered capability in one execution instead of selecting a bounded first loop.
- **phase-delegation burden** — asking the user to decide how to split the product instead of
  deriving the boundary from dependencies, user value, and execution constraints.
- **layer slice** — presenting a page, schema, service, or plan as a complete vertical deliverable.
- **ask-instead-of-recover** — asking the user for understanding the system should infer from the
  seed and existing artifacts.
- **vibe-sprint-under-deadline** — "pick one, go fast" energy that manufactures drift and false
  completion.
- **literal-ask-over-full-intent** — treating the minimal prompt as the requested output size.
- **trim-without-authority** — deferring or cutting features and labeling them done or closed
  without the user's scope decision.
- **partial-start-before-info-complete** — beginning the active deliverable before the information
  to perform and verify that deliverable is in hand.
- **future-input blockade** — refusing an independent first loop because a later deliverable's
  non-dependent input is not yet available.
- **convenient-target adoption** — choosing a builder such as Sites because it is available even
  though the production product requires operational data, permissions, backend workflows, or
  established-repository integration.
- **false-choice-when-both-required** — offering the user an either/or between options that are
  all needed. If both (or all) are required, do them all; a non-decision is not a question. Only
  a genuine, mutually exclusive, outcome-changing fork is worth asking.

## The measure

Track **correction-rounds-to-correct-checkpoint**: how many user corrections were needed before
the checkpoint matched intent. Zero is the goal. A session that needs many corrections to reach
correct scope is the failure this gate exists to erase — record it through
[feedback-and-learning-loop.md](feedback-and-learning-loop.md) and harvest the corrections into
new guards via [correction-harvesting.md](correction-harvesting.md).

Track **wanted-result match** at every handoff. If the person says or the acceptance evidence
shows that the result is not what they wanted, the value is failed and Step 1 reopens regardless
of code quality, test status, quota limits, or how reasonable the substitute appears. An external
constraint may make completion blocked; it cannot make the mismatched result aligned.

## Relationship to the modes

The checkpoint is the mandatory front door for build-shaped work; it is not a new mode. Start
mode then executes it (Before-build locked), the friction ladder sets how much ceremony each
slice earns, the council runs the active deliverable, and the Resume Packet carries the later
deliverable map and next safe action across contexts.

## Relationship to live steering and model interchangeability

The full-scope first-checkpoint artifact locks recovered intent, decomposition, proof, and
authority before a build. **Live steering** keeps that lock interchangeable across models:
the first run-loop checkpoint is always **“What I understand you want,”** side effects stay
blocked until approval, and Correct / `CORRECT:` forces interrupt → `RETRACT`/`REPLACE` →
new checkpoint → re-approve before any drifted action runs.

**Surface rule:** Platynum may show clickable Approve/Correct. Outside Platynum (skill prompts,
Cursor, IDE agents), do **not** display decorative Approve/Correct controls—use the text gate
`APPROVE` or `CORRECT: <instruction>` only. SI runtime enforcement is in
[step1-intent-control-status.md](step1-intent-control-status.md). Read
[model-neutral-execution.md](model-neutral-execution.md#governing-requirement-model-interchangeability)
and [guided-council.md](guided-council.md#pre-action-intent-steering). Do not invent halt-all,
restart-project, or new-branch policies from a correction.
