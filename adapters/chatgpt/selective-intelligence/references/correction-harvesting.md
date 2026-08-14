# Correction Harvesting

Use this workflow when the user cannot remember every prior AI failure, refers to repeated corrections, or asks to turn experience into durable intelligence.

## Principle

The user should not have to author a retrospective failure taxonomy. Recover available evidence and transform it into reusable prevention.

## Sources

Inspect only sources available and relevant to the authorized scope:

1. Current conversation and direct corrections
2. Available personal conversation context
3. Locked product doctrine and decision records
4. Repository history, issue threads, pull-request reviews, and review packets
5. Repeated test fixes and regression guards
6. Support incidents, QA findings, and production discrepancies
7. Prior generated artifacts and user rejection patterns
8. Local structured outcome signals from `.selective-intelligence/feedback/events.jsonl`

Do not blend project-specific doctrine across brands or infer a universal preference from one isolated complaint.

Prefer the privacy-preserving events and aggregate causes defined in [feedback-and-learning-loop.md](feedback-and-learning-loop.md). Do not mine raw prompts, hidden reasoning, secrets, or personal data merely to improve the skill.

## Normalize each correction

Capture:

| Field | Meaning |
|---|---|
| Trigger | What the user asked or expected |
| Wrong result | What the AI actually did |
| Actual intent | What should have become true |
| False assumption | Why the AI believed its result was acceptable |
| Failure class | The general pattern beyond this instance |
| Detection signal | What repository or product evidence exposes it |
| Prevention gate | What must happen before implementation or handoff |
| Verification | What proves the failure is absent |
| Scope | Universal, software-wide, product-specific, or one-off |

Preserve sharp distinctions and negative requirements. User corrections such as “both, not either,” “exists, not reachable,” “implemented, not live,” or “search, not chatbot” often define the real contract more precisely than broad positive descriptions.

## Promotion rules

- Promote a pattern into the general Selective Intelligence gates when it recurs across projects or exposes a fundamental AI reasoning failure.
- Keep product doctrine in that product's authoritative context.
- Keep one-off aesthetic choices local unless the user explicitly generalizes them.
- Merge with an existing failure class when the causal pattern is the same.
- Create a new gate when existing rules would not reliably detect or prevent it.
- Promote immediately when one event exposes a severe truth, safety, authority, privacy, destructive-action, or false-completion defect.
- Otherwise require recurrence across independent runs or contexts before generalizing beyond the project.
- Pair every promoted gate with a reproducible fixture and a signal that can show whether recurrence falls.

## Future-session behavior

When a user correction occurs:

1. Fix the immediate result.
2. Search the active scope for sibling violations.
3. State the generalized rule internally.
4. Add a project regression guard when appropriate.
5. If the user is actively refining Selective Intelligence, update the durable failure corpus.
6. Record the corrected outcome and cause so the next improvement pass needs minimal user research.

Do not pause delivery merely to document the lesson. The corrected user outcome remains primary.

## Periodic backfill

When asked to deepen the skill, mine history in bounded categories rather than one overwhelming search. Useful passes include:

- intent and scope failures;
- architecture, duplication, and drift;
- UI/UX and output-medium failures;
- testing and false-proof failures;
- deployment, runtime, and operational failures;
- permissions, identity, and authority failures;
- communication, burden-shifting, and false-status failures.

Deduplicate the results, preserve source distinctions, and validate new gates with realistic forward tests.

The learning cycle is complete only when the correction is reproduced, generalized, implemented as a narrow rule or validator, forward-tested, released, and watched for recurrence. Documentation alone is not learning.
