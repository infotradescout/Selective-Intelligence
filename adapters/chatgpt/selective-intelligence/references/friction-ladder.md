# Friction Ladder

Use this when deciding how much process a piece of software work deserves. The ladder
scales ceremony to consequence instead of choosing a mode up front, so scratch
prototyping stays fast while durable work keeps its full guardrails. It complements the
operating modes; it does not replace [references/start-mode.md](start-mode.md) or
[references/operational-safety-gates.md](operational-safety-gates.md).

The governing rule: **friction is proportional to what the work can affect, and work is
allowed to graduate.** Reduce ceremony, never the two non-negotiable guardrails.

For Selective Intelligence, if work is not a genuine throwaway local sketch, it runs as **Tier 1** through JumpStart and all related lanes.

## Contents

- [The two non-negotiable guardrails](#the-two-non-negotiable-guardrails)
- [Tier 0 — Scratch](#tier-0--scratch)
- [Promotion gate: Tier 0 to Tier 1](#promotion-gate-tier-0-to-tier-1)
- [Tier 1 — Product](#tier-1--product)
- [Choosing the tier](#choosing-the-tier)

## The two non-negotiable guardrails

These hold at every tier, including a throwaway one-file script:

1. **No unauthorized external effect.** Never send, publish, push, merge, delete,
   purchase, provision a paid service, change permissions, accept terms, or disclose
   sensitive data outside its approved boundary without explicit, comprehensible
   authority for that exact action and target. A tool's availability is not permission.
2. **No unproven completion claim.** Never state that something was tested, sent, saved,
   approved, published, pushed, deployed, live, or complete without corresponding
   evidence. Label unverified structural claims `manual_unverified`.

Everything else on this page is ceremony, and ceremony is what scales.

## Tier 0 — Scratch

**When:** a single file or session, local only, no persistence, no shared state, no real
users, and no money — or the user explicitly asks to prototype, sketch, or throw ideas
at the wall.

**Do:** build immediately. Skip the Intent Lock, the Worker/Objector/Aligner Council,
the Start Pack, and the seal. Leave exactly one artifact of process: a one-line
assumption note stating the reversible interpretation you chose.

**Do not:** demand a questionnaire, a mode selection, a schema, or an installation step
before writing code. Do not manufacture drift by locking architecture the work has not
earned.

## Promotion gate: Tier 0 to Tier 1

Escalate the moment **any** of these first appears:

- persistence (a database, a file the work will re-read, saved state);
- shared mutable state or more than one caller/tenant;
- a real user other than the author;
- money movement, credits, entitlements, or a payment path;
- an external deployment, publish, push, or send;
- an explicit intent to keep, maintain, or return to the code.

On promotion, run the minimum reconciliation before scaling:

1. Write a brief **retroactive Intent Lock**: desired outcome, primary user/job,
   non-negotiables, prohibited outcomes, scope boundary, success proof, authority, and
   the sensitive-data and spending boundaries.
2. Run **one Objector pass** over the scratch code: unrouted surfaces, broken or unmet
   APIs, logical drift, mismatched dependencies, and any false-completion claim.
3. Dispose each finding against the lock, correct sustained ones, and only then treat
   the work as Tier 1.

Promotion is a checkpoint, not a rewrite. Preserve what already works; add the
governance the higher stakes now require.

## Tier 1 — Product

**When:** new products and durable work — anything past the promotion gate.

**Do:** use the full Start-mode contract. Create or adopt the proportional Start Pack,
validate its machine-readable control graph, obtain a **Before-build locked** verdict
before creating project code, run the Council, apply the risk-triggered operational
safety gates, and seal the state. Reconcile planned versus actual behavior after each
build and establish the next truthful baseline.

## Choosing the tier

- Default a genuinely exploratory, local, single-session request to **Tier 0**.
- Default anything with users, persistence, money, or an external effect to **Tier 1**.
- When the tier is unclear, name the assumption and choose the **lighter** tier that
  still protects the two non-negotiable guardrails, then promote as soon as a trigger
  appears. Under-ceremony on a throwaway is cheap; a missed guardrail is not, which is
  why the guardrails never scale down.
