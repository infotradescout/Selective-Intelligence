# Time Awareness

Selective Intelligence stamps its work and stays aware of time passing. Time is evidence: it
tells you how stale a fact is, how long work has taken, whether a deadline is real, and whether a
prior result can still be trusted.

## Contents

- [Timestamp the work](#timestamp-the-work)
- [Be aware of time passing](#be-aware-of-time-passing)
- [Time in handoffs and resumes](#time-in-handoffs-and-resumes)
- [Truthfulness](#truthfulness)

## Timestamp the work

- Stamp every durable work product — checkpoint, Start Pack seal, evidence report,
  handoff/Resume Packet, feedback signal — with a UTC timestamp in ISO 8601
  (e.g., `2026-07-22T21:30:00Z`).
- Record what produced it and at which revision, so a later context knows the age and origin of
  what it inherits.
- Convert relative time ("today", "in a day", "recently") to absolute timestamps at capture;
  relative words rot.

## Be aware of time passing

- Note when a session or task starts and track elapsed time; report durations honestly
  ("built over ~40 min", not "instantly").
- Treat deadlines as scope-sequencing input, never as authority to cut scope or claim unproven
  completion (see [first-checkpoint.md](first-checkpoint.md)).
- Flag staleness: when a fact, price, plan, model, or external source carries an observed date,
  revalidate it when that date changes or a freshness window lapses (aligns with the
  volatile-facts rule in `SKILL.md`).

## Time in handoffs and resumes

- A Resume/handoff packet records wall-clock time so the receiving context knows how old the
  state is and whether external effects may have changed since it was written.
- When resuming, compare the current time to the packet's timestamp; treat long gaps as a reason
  to re-inspect actual state before mutation.

## Truthfulness

- Never fabricate a timestamp or backdate work. If the real time is unknown, say so rather than
  inventing one.
