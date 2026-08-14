# Non-Developer Surface

Selective Intelligence builds for vibe coders, not developers. The user never has to do a
developer's job to use what you build. This is a hard gate: if a surface, connector, or step
requires developer knowledge or credential handling, it is wrong — fix the architecture, do not
hand the task to the user.

## Contents

- [The only things the user does](#the-only-things-the-user-does)
- [Present plans as 1-2-3, not doctrine](#present-plans-as-1-2-3-not-doctrine)
- [The rule](#the-rule)
- [The architecture principle](#the-architecture-principle)
- [Language](#language)
- [Enforcement](#enforcement)
- [Failure harvested](#failure-harvested)

## The only things the user does

The human layer is minimal. Across the entire build, the user should never have to do anything
except these four, and nothing else:

1. **Answer a question** — only when a missing answer would materially change the product,
   authority, sensitive-data boundary, cost, or an irreversible choice. Asked in plain language,
   consolidated up front, with a recommended default.
2. **Take the alignment / authority steps** — approve the genuine human decisions the AI cannot
   self-grant (irreversible actions, spend, consent, sensitive-data boundaries, brand, external
   mutation). This is how the human stays the authority.
3. **Connect a third-party source** — one click to authorize their own models and sources; the AI
   never asks them to handle the mechanics behind it.
4. **Take an action only a human can** — something the AI literally cannot or must not do
   (physical-world, identity-bound, or prohibited actions).

Everything else — recovering intent, planning, building, wiring, verifying, fixing, reconciling —
is the AI's job, not the user's. If the user is doing anything outside these four, that is a
failure of the surface to absorb the work.

## Present plans as 1-2-3, not doctrine

Keep the complete checkpoint, Council roles, proof contract, and activation ledger inside the
engine and its durable artifacts. The person using the product sees the same truth translated
into a short numbered build path: what will be built, in what order, what they will get, and the
few things only they can do. Do not expose doctrine field names, model deliberation, architecture
essays, raw agent output, or unexplained proof jargon as the primary product surface.

Plain presentation is not permission to omit requirements. The engine must retain the full
machine-checkable artifact and bind the numbered steps to it; the user-facing plan is a view of
the checkpoint, not a replacement for it. If the user must interpret AI scaffolding to know what
happens next, the surface has failed to absorb the intelligence work.

## The rule

Never require the user to obtain, paste, or manage any of:

- API keys, access tokens, or secrets — including "personal access tokens", OAuth client
  secrets, or picking "repo scope";
- keys pasted into chat or form boxes;
- environment variables, `.env` files, or config files;
- CLI commands, package installs, or build steps;
- provider dashboards, developer settings, or scope/permission jargon.

Replace each with a one-click flow ("Connect GitHub" → authorize → done) or a plain-language
choice. The mechanics (tokens, scopes, exchange) happen behind the surface; the user sees a
button and an outcome.

## The architecture principle

If a capability cannot be delivered without exposing developer mechanics, that is an
**architecture gap to fix — not a step to hand the user.** A pure-static / no-backend design
that forces the user to paste a token has chosen developer burden over user experience; add the
minimal broker or one-click flow instead. Never ship the developer wall as the user path — and
never disguise it as the "advanced" path while leaving it as the only path.

## Language

- Plain language only on any user-facing surface. No routing, API, dependency, token, scope,
  env, or CLI vocabulary.
- Explain outcomes ("your changes are live"), not mechanics ("committed SHA … triggered CI").

## Enforcement

This gate is not satisfied by being written here. It is enforced by:

- an eval case that **fails** when a build asks the user for a token, key, scope, env var, or CLI
  command;
- the product surface (e.g., Platynum-47) refusing to present such a step to the user.

A prose rule the model can read and violate is not enforcement; the check and the product are.
See [first-checkpoint.md](first-checkpoint.md) for why documented ≠ enforced.

## Failure harvested

Origin: a GitHub connector shipped a "paste a personal access token (repo scope)" field into a
non-developer product. That is the exact wall this gate exists to stop.
