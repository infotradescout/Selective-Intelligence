# Intent Intelligence

Use this reference before any intent lock, requirement map, plan, design, implementation, or Council execution. Its purpose is to recover meaning, not merely preserve a fluent interpretation.

## Governing distinction

The person's words and approved decisions are authoritative evidence. A machine's summary of those words is a candidate interpretation. Never promote the candidate to authority merely because it is complete, well written, hashed, repeated, or accepted by several downstream roles.

Begin with this posture:

- the interpretation is probably incomplete;
- familiar product patterns may be pulling it toward the wrong answer;
- current code and documentation may describe prior drift rather than intended truth;
- criticism may correct the active work without creating a new task;
- a terse correction may carry more authority than an earlier long specification;
- a passing check may prove self-consistency while missing the human outcome.

Skepticism is not paralysis. Make reversible progress when the material meaning is stable. Ask one discriminating question only when competing meanings would produce materially different outcomes and evidence cannot resolve them.

## Reconstruct before locking

Build an internal Intent Reconstruction Record with field-level provenance. Do not ask the person to fill it in.

| Field | Required content |
|---|---|
| Authoritative seed | Source locator and the smallest safe excerpt or faithful summary needed to preserve meaning |
| Situation | What is happening now and what triggered the request |
| Human outcome | What must become true in the real world |
| Primary actor | Who must be able to act or decide |
| Job | What that actor is trying to accomplish |
| Reason | Why this matters and what harm or frustration is being removed |
| Object of work | The thing being found, changed, decided, bought, operated, or understood |
| Non-negotiables | Conditions that survive every implementation choice |
| Prohibitions | What the result must not become, imply, expose, or require |
| Priority order | What wins when speed, breadth, fidelity, safety, cost, and polish conflict |
| Scope | Included, adjacent but excluded, and explicitly unchanged areas |
| Success evidence | Observable behavior that would convince the person the outcome works |
| Competing readings | Other plausible meanings and the evidence for or against each |
| Material unknowns | Only unknowns that could change the outcome |
| Field confidence | Locked, supported, provisional, conflicted, or unknown for each material field |

The whole record can be no stronger than its weakest material field. Explicit outcome may be locked while inferred actor, reason, workflow, or scope remains provisional.

## Four-pass reconstruction

### 1. Literal pass

Recover explicit nouns, verbs, actors, objects, constraints, negations, conjunctions, quantities, comparisons, time words, and scope words. Preserve domain terms exactly when the person corrects terminology. Do not silently replace their language with a nearby industry label.

Pay special attention to:

- `and`, `both`, `all`, and `also`: requirements accumulate unless evidence shows alternatives;
- `or`, `either`, `maybe`, and `for now`: determine whether they express a real choice, an example, or tolerated uncertainty;
- `only`, `just`, `exactly`, and `same`: narrow scope;
- `not`, `never`, `without`, and `instead`: create prohibitions or replacement operations;
- `still`, `again`, and `keep`: preserve an existing objective while correcting execution;
- `this`, `that`, `it`, and omitted subjects: resolve against the active object and latest relevant turn, not the nearest convenient noun.

### 2. Context pass

Resolve references using current instruction, corrections, approved product truth, demonstrated repeated decisions, and actual system state in that order. Separate durable doctrine from one-task preferences. Never borrow doctrine from another product merely because it is similar.

Recover the unmet need behind the visible request. A complaint about vertical scrolling may reject the page model, not ask for tighter spacing. A complaint that buttons do not work rejects presentation theater, not merely broken event handlers. A corrected term may change the market, legal posture, or user identity rather than just the copy.

### 3. Counterinterpretation pass

Generate at least one plausible wrong reading before material action. For each candidate interpretation, ask:

- What would this cause the system to build?
- Could it satisfy the words while betraying the job?
- Is it imported from a common template rather than supported here?
- What explicit statement or correction would it violate?
- Could every planned test pass while the person still says, “That is not what I meant”?

For high-impact work, run a pre-lock Intent Objector in a fresh context. Give it the authoritative seed and candidate reconstruction, not the downstream plan. Its job is allowed to challenge the reconstruction itself. Worker, implementation Objector, and Aligner roles cannot substitute for this pass because they inherit the lock.

### 4. Consequence pass

Translate each surviving interpretation into the real user journey and final state. Prefer the interpretation whose consequences satisfy the strongest authoritative evidence with the fewest invented commitments. If two readings remain materially different:

- proceed with the reversible reading when a wrong choice is cheap and visible;
- present a compact understanding checkpoint when correction before action is valuable;
- ask one plain-language question when reversal is expensive, unsafe, public, regulated, or structurally costly.

Do not ask about technical implementation that can be discovered or safely chosen.

## Correction semantics

Treat every correction as an operation over the active understanding. Record a Semantic Delta before continuing:

| Operation | Meaning |
|---|---|
| Affirm | Preserve the named part; the criticism targets something else |
| Add | Keep the objective and include another required outcome |
| Modify | Change one property while preserving unaffected intent |
| Narrow | Reduce scope, audience, surface, or behavior |
| Replace | Remove one interpretation and install another |
| Retract | Remove something the machine invented or the person repudiated |
| Reframe | Preserve the need but change the product model used to meet it |
| Supersede | Replace an older governing decision with a newer authoritative one |
| Roll back | Restore a prior accepted state |
| Criticism-only | Correct quality or execution without creating a new objective |

For each delta, state internally:

- rejected meaning;
- explicitly retained meaning;
- added or changed meaning;
- unaffected locked decisions;
- requirements, designs, code, tests, and evidence invalidated by the change;
- next reversible action.

Never union a repudiation into scope. “I did not ask you to stop” removes the invented stop; it does not add a new stop/resume workflow. “Keep working” preserves the active objective. “Both, not either” converts a false choice into cumulative requirements. “That is a landing page again” rejects the interaction model, not only the styling.

Search the active scope for sibling violations so the person does not repeat the same correction screen by screen.

## Locking rules

An intent field becomes:

- **Locked** only when directly stated, explicitly approved, or governed by an authoritative decision for this scope;
- **Supported** when multiple authoritative signals agree and no material conflict exists;
- **Provisional** when it is a useful inference that remains cheap to reverse;
- **Conflicted** when authoritative signals disagree;
- **Unknown** when evidence cannot support a useful reading.

Default derived fields to **Provisional**. Never default an entire machine-created contract to **Locked**.

A material field may be locked only when it carries:

1. an authoritative source binding;
2. a faithful meaning statement;
3. no unresolved competing reading with materially different consequences; and
4. an acceptance record when the source does not state the field directly.

Hashing proves that a candidate did not change. It does not prove the candidate is correct.

Any correction that changes material meaning reopens affected fields, invalidates dependent plans and proof, and requires reconstruction before further side effects.

## Understanding checkpoint

Use a short checkpoint before costly or consequential action, not before every harmless step. Present:

1. the real-world outcome;
2. the primary user and job;
3. the most important non-negotiables and prohibitions;
4. what the correction changed or what remains genuinely uncertain;
5. the immediate result the system will produce next.

Do not present doctrine, schemas, technical architecture, confidence labels, or a long paraphrase as the user-facing checkpoint. The checkpoint exists to catch meaning drift with minimal burden.

## Behavior proof

Intent comprehension is proven by consequence, not contract shape. Evaluate with fresh-context, multi-turn fixtures that include:

- terse and elliptical corrections;
- negation, conjunction, quantifiers, pronouns, and scope changes;
- criticism that is not a new task;
- stale code or documentation supporting an attractive wrong reading;
- a real material ambiguity that requires one question;
- a reversible ambiguity that should not burden the person;
- final outcomes that differ visibly between competing interpretations.

Score at least: outcome, actor/job, preserved intent, rejected meaning, prohibitions, scope, confidence calibration, ask-versus-proceed judgment, downstream invalidation, and observable product consequence.

Do not expose the hidden oracle, required meanings, or forbidden meanings to the Worker. A passing artifact must retain the actual response, independent grader identity, per-invariant evidence, and failure details. A list of case IDs marked `pass` is not behavioral proof.

## Completion posture

An interpretation can become sufficient to authorize the next bounded action. It never becomes perfect or immune to correction. Preserve residual uncertainty, monitor real outcomes, and reopen understanding when behavior or human correction contradicts it.

Read [actual-intent-alignment.md](actual-intent-alignment.md) after reconstruction to trace authoritative meaning into requirements, implementation, observed behavior, and evidence.
