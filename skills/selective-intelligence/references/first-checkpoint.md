# First Checkpoint

The first response to any build-shaped request is a locked, full-scope intent checkpoint —
recovered from minimal input — not code, not a trimmed deliverable, not a permission request.
No part of the build begins until this checkpoint is complete **and every input needed to
perform the entire outcome is in hand.** This is the gate that makes minimal input produce
complete outcomes. The skill's readiness is measured by how few correction rounds a user needs
to reach a correct checkpoint; the target is zero.

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
   minimal ask. Treat the prompt as a seed, never as the output size. Scoping the deliverable
   down to fit available effort or time is forbidden here.
2. **Whole-product decomposition** — the complete system as bounded slices (tiers), each with
   inputs, outputs, an owner, and its proof. No slice is dropped for being hard or large.
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

Stamp the checkpoint with a UTC timestamp and carry it forward (see
[time-awareness.md](time-awareness.md)).

## Information sufficiency before execution

No part of the build starts until every input needed to perform the entire outcome is in hand.

- **Recover first.** Fill the information by inference from the seed, the repository, connected
  evidence, and established constraints before considering a question.
- **Resolve genuine unknowns in one consolidated, up-front pass** — only the few answers that
  would materially change the product, authority, sensitive-data boundary, consequential cost,
  or an irreversible choice. Ask them together, once, in plain language, with recommended
  defaults.
- **Never trickle-ask mid-build, and never begin a slice while a later slice's blocking inputs
  are still unknown.** Partial starts on partial information are drift.

## Enforcement

- No application code, no trimmed deliverable, and no permission-per-step before the checkpoint
  exists and is information-complete.
- Present the checkpoint, then execute under the authority split — confirming only the genuine
  decisions, once, not each step.
- Scope-reduction and single-threading are drift, not prudence. "Smallest viable release"
  sequences the full outcome; it never shrinks it.
- A deadline is not authority to cut scope, skip the checkpoint, or claim completion without
  evidence.
- If the delivered result is not what the person wanted, Step 1 failed and reopens. Do not
  downgrade the wanted outcome to match a free-tier quota, unavailable tool, external company
  boundary, implementation shortcut, or technically successful substitute. Record the
  constraint, recover the missed meaning or path, and correct it. Only an explicit user-approved
  amendment made after the difference is clear can change the target.

## Failure classes this gate refuses

Mined from real correction sessions; each is a named guard:

- **scope-reduction-as-completion** — trimming the deliverable to fit one thread or one day and
  calling it done.
- **single-thread default** — building one file at a time instead of decomposing for parallel or
  council execution.
- **ask-instead-of-recover** — asking the user for understanding the system should infer from the
  seed and existing artifacts.
- **vibe-sprint-under-deadline** — "pick one, go fast" energy that manufactures drift and false
  completion.
- **literal-ask-over-full-intent** — treating the minimal prompt as the requested output size.
- **trim-without-authority** — deferring or cutting features and labeling them done or closed
  without the user's scope decision.
- **partial-start-before-info-complete** — beginning any slice before the information to perform
  all of it is in hand.
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
slice earns, the council runs the slices, and the Resume Packet carries state across contexts.

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
