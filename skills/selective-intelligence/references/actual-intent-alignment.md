# Actual Intent Alignment

Use this reference whenever the work claims to align, realign, correct, complete, reconstruct, or implement a user's intended product or system.

First apply [intent-intelligence.md](intent-intelligence.md). This reference traces reconstructed meaning into product behavior; it does not make a machine interpretation authoritative. The person's words may be authoritative while the machine's normalization remains provisional.

## Contents

- [The distinction](#the-distinction)
- [Build the intent authority map](#build-the-intent-authority-map)
- [Form the intent contract](#form-the-intent-contract)
- [Assign intent confidence](#assign-intent-confidence)
- [Apply the material-assumption test](#apply-the-material-assumption-test)
- [Create the intent trace](#create-the-intent-trace)
- [Run the counterfactual check](#run-the-counterfactual-check)
- [Alignment verdicts](#alignment-verdicts)
- [Handoff rule](#handoff-rule)

## The distinction

**Perceived alignment** means the implementation resembles an agent's interpretation, existing code, common practice, or nearby language.

**Actual alignment** means authoritative user intent is explicitly represented by product behavior and verified against observable acceptance criteria.

Similarity is not traceability. A plausible implementation is not proof of intent. Existing code proves only that something was built.

## Build the intent authority map

Use evidence in this order unless an explicit governance system defines another order:

1. Current direct instruction from the authorized user
2. Explicit locked decisions, corrections, and non-negotiables for the same product
3. Approved product contracts, governance records, and acceptance criteria
4. Repeated, consistent user decisions demonstrated across the same system
5. Current canonical behavior when it has been explicitly accepted
6. Documentation, tests, and code as supporting evidence only
7. General conventions, analogous products, and agent inference as provisional inputs only

More recent wording does not automatically overturn a durable locked decision if it addresses a different scope. Resolve scope before declaring conflict.

## Form the intent contract

Capture these elements internally before editing:

| Element | Required question |
|---|---|
| Outcome | What must become true for the user? |
| Primary user | Whose experience or authority governs this work? |
| Job | What must that person be able to accomplish? |
| Reason | Why does the outcome matter? |
| Non-negotiables | What must remain true regardless of implementation? |
| Prohibitions | What must the product never become or imply? |
| Tradeoffs | What wins when goals conflict? |
| Completion proof | What observable behavior would convince the user it is done? |
| Scope boundary | Which adjacent systems or brands must remain untouched? |

Record negative corrections. “Do not sell leads,” “Scout is search, not a chatbot,” or “do not require the user to manage two surfaces” often carry more precise intent than generic feature descriptions.

Bind every material field to its own provenance and confidence. Do not assign one global `locked` label to a contract containing inferred actor, reason, workflow, priority, scope, or success proof. The whole-contract verdict can be no stronger than its weakest material field.

## Assign intent confidence

- **Locked:** directly and authoritatively stated, approved, or governed.
- **Supported:** consistent across multiple authoritative decisions with no material conflict.
- **Provisional:** a reasonable working interpretation that has not been authoritatively confirmed.
- **Conflicted:** authoritative evidence points to materially different outcomes.
- **Unknown:** evidence is insufficient to form a useful interpretation.

Only Locked or Supported material intent may receive an **Aligned** verdict. Provisional intent may guide reversible progress, but the status must remain **Provisionally aligned**. Machine fluency, hashes, schema validity, or agreement among roles never upgrades confidence.

## Apply the material-assumption test

Before acting on an unconfirmed interpretation, ask:

1. Could the user reasonably say, “That is not what I meant,” even if the implementation is technically good?
2. Would the interpretation change the core user journey, business model, authority, identity, data handling, brand, or irreversible architecture?
3. Is the choice expensive or dangerous to reverse?

If yes, inspect existing authoritative context first. If it remains unresolved, ask one product-level question with a recommended interpretation and its consequence. Do not ask the user to choose technical details that do not change the intended outcome.

## Create the intent trace

For each material intent rule, trace:

`authoritative intent → product requirement → implementation surface → observed behavior → validation evidence`

Also trace prohibitions:

`prohibited outcome → prevention mechanism → regression guard → observed absence`

An intent rule with no implementation surface is missing. An implementation surface with no authoritative intent may be scope drift. A test that asserts the wrong requirement is automated misalignment, not proof.

## Run the counterfactual check

Before declaring alignment, test these questions:

- If the technical symptom disappeared, would the user's actual problem be solved?
- Could every test pass while the user still says the product is wrong?
- Did the solution optimize a local component while violating the end-to-end job?
- Did a familiar industry pattern overwrite a product-specific decision?
- Did the implementation preserve a prohibited behavior under new wording?
- Did the agent confuse “present in code” with “available to the intended user”?

Any “yes” blocks an Aligned verdict.

Use the simplest final counterfactual: **Is this result what the person wanted?** If the answer is
no, Step 1 failed. Reopen the intent checkpoint and trace the mismatch; do not defend the result
with technical quality, available tooling, cost, a free-tier boundary, or another external
constraint. A truthful external block remains Blocked or incomplete against the original intent.
It becomes a different intended outcome only after the person explicitly approves that change
with the material difference visible.

Also ask whether the active Council could rigorously validate the wrong premise because every role inherited the same candidate lock. When that is possible, return to the pre-lock Intent Objector rather than adding another downstream reviewer.

## Alignment verdicts

- **Aligned:** Locked or Supported intent is traced to verified observable behavior, with material prohibitions protected.
- **Provisionally aligned:** A reversible implementation matches the best available interpretation, but intent is not authoritative enough for a final verdict.
- **Partially aligned:** Some authoritative requirements are satisfied and named gaps remain.
- **Not aligned:** Observed behavior contradicts one or more authoritative requirements.
- **Unverifiable:** Intent or product evidence is insufficient to judge.

Never use “aligned” as a synonym for polished, coherent, conventional, passing, or implemented.

## Handoff rule

Lead with the user outcome. State the alignment verdict only when useful, and name the evidence class behind it. If the verdict is provisional or unverifiable, identify the single smallest decision or observation needed to establish actual alignment.

## Guided Council binding

A Council packet carries an exact Intent Lock snapshot or digest; a role response cannot redefine it. Bind every objection to a finding ID and an exact claim, requirement, artifact, path, permission, evidence reference, or completion assertion. The Aligner must disposition each finding once against governing intent and evidence, not against provider reputation or vote count.

A rejected finding cites the stronger intent rule and evidence. A sustained material finding names affected requirements, invalidated proof, correction ownership, and required revalidation. A blocking sustained or still-open finding prevents a passing workflow gate. The alignment verdict and workflow gate remain separate: a product may be partially aligned while the next safe action is a correction, human decision, or block.
