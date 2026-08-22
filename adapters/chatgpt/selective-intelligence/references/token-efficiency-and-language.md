# Token efficiency and human language

Token efficiency is the first operating priority because wasted context causes
wasted work, drift, and more correction. It never means silently shrinking the
wanted outcome or dropping proof.

## Prompt budget

- Keep the canonical `SKILL.md` under 1,500 words and 12,000 characters. Release validation fails above either limit.
- Start Lean work with the master skill only: zero reference files, zero role packets, and one active execution context.
- Load at most one reference before the first useful action. More is justified only by a documented safety trigger or an explicitly selected Council lane.
- Do not copy the full doctrine, conversation history, or implementation narrative into a reviewer packet. Send only the outcome, prohibitions, relevant evidence, authority boundary, artifact, and proof question.
- Prefer deterministic searches, validators, indexes, and targeted line ranges over prose summaries or broad file ingestion.

Measure total task cost. A short final answer does not compensate for several duplicated contexts, automatic role handoffs, or references loaded without changing a decision.

## Spend in this order

1. Recover the real intent before generating a plan or code.
2. Inspect the current system and select only context that can change the next decision.
3. Reuse the canonical owner instead of generating another version.
4. Build and verify the result.
5. Report the result, proof, limitation, and next material fact in the fewest useful words.

Do not spend context on files merely because they sort first, restating the
prompt, repeating settled decisions, generic encouragement, hidden alternatives,
or long progress narration. An explicitly named file wins. Otherwise rank files
by objective, task, acceptance criteria, path, source-content, canonical-owner, and local dependency relevance.
Keep hard file and byte limits, exclude secret-like and binary content, and emit
the selection reasons plus estimated selected and avoided tokens. Estimates must
be labeled estimates.

## Write like a person

Use concrete nouns and verbs. Say what changed, what works, what failed, and what
is still unknown. Prefer “The mobile menu opens and closes” to “The experience
has been enhanced.” Delete any sentence that could be pasted into an unrelated
project unchanged. Do not pad a short answer with headings, recaps, throat
clearing, praise, slogans, or generic claims about robustness and seamlessness.

Technical terms are useful when they identify evidence or a real constraint.
They are not useful as decoration. Never hide a missing result behind polished
language.

## Completion check

- Did misunderstanding create avoidable work or repeated context?
- Did the run remain Lean unless a real escalation trigger was recorded?
- Was no more than one reference loaded before useful action?
- Was every selected file relevant to the next decision or required proof?
- Was an existing owner reused before new code was proposed?
- Does every user-facing sentence carry a result, decision, proof, limit, or required action?
- Could the same truth be said more directly without losing a guardrail?
