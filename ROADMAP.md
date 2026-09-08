# Roadmap

## Product outcome and runtime audit — September 8, 2026

The user's current product goal is that Selective Intelligence solves AI drift,
duplication, unnecessary compute and storage, and enables a vibe coder to complete
full-stack development. SI must carry an ordinary-language request through the
technical work needed for a working result: preserve intent, reuse existing owners,
choose relevant context and tools, build the necessary frontend/backend/data paths,
verify them, preserve progress, and deliver within the user's authority.

An AI harness describes the machinery supporting this outcome. A token limiter,
collection of prompts, successful unit suite, or generated frontend alone does not
prove the product outcome. The user's latest corrections govern the work.

### Instructed, implemented, and verified

Audit baseline: repository revision `d15220aea58553b08d9f577cf527ff3118f42edf`.
The changes described as this branch require integration and client adoption before
they can be called installed behavior. No Platynum installation was tested in this audit.

| Responsibility | Instructed | Runtime implementation | Evidence and remaining boundary |
| --- | --- | --- | --- |
| Preserve intent and prevent drift | Canonical SKILL and intent/checkpoint contracts | `intent_contract.py`, `checkpoint.py`, `build_engine.py`: current intent/checkpoint binding, invalidation, correction, guarded writes | Existing production-path and correction tests exercise local transactions. Rich conversational interpretation and equivalent behavior across clients remain unproved. |
| Avoid duplicate implementations | Reuse the canonical owner before creating another | `project_index.py` detects exact source duplicates and component/hook collisions; this branch connects prospective checks to artifact application | Test introduced duplication and inherited debt separately. General semantic duplication is beyond this detector's evidence. |
| Avoid unnecessary compute/context | Whole-run usage governor, bounded retrieval, one owner per question | This branch connects `progress_checkpoint.py` admission to worker retrieval, persists per-task windows, caps complete handoffs, and preserves excluded dependency identities in coverage | Focused engine tests include process restart, concurrent admission, failed retrievals, and both packet/build serialization. Other model calls, arbitrary host tool use, repository scan cost, and provider billing are outside this boundary. |
| Avoid unnecessary storage/writes | Preserve coherent progress and reuse artifacts | Session storage is atomic; temporary write stages are cleaned; this branch recognizes unchanged target bytes during artifact application | Unchanged files must not be rewritten or claimed as new writes. Long-term history retention, checkpoint compaction, and storage budgets still need implementation with proof-reference preservation. |
| Resume work | Recover from durable current state without retelling old chats | `lane_session.py` persists queues, intent, evidence, and transactions; progress helper supports explicit commit/push checkpoints | Local persistence is tested. Default session storage is temporary unless the host sets a durable `SI_SESSION_DIR`; automatic host invocation and checkpoint cadence remain integration gaps. |
| Execute full-stack work | Product-complete output and developer-grade execution | Engine accepts source-bound plans and worker artifacts, applies policy checks, runs allowed verification, and creates repair tasks | The packet-to-apply-to-verify path is locally executable. Capability probes are not a model dispatcher; no automatic model/tool execution loop was found in the inspected integration paths. |
| Prove and deliver the real result | Distinguish implemented, proved, pushed, integrated, deployed, and live verified | Task-bound command evidence and completion checks exist; behavioral-evidence validation exists | Current 1.0.8 model evaluation says `not_run`. The legacy live eval caller's v1 output does not supply the captured outputs required by the v2 validator. Full-stack live completion and cross-client equivalence are not established. |

### Remaining work in outcome order

1. Integrate and verify the runtime admission/reuse changes in the actual client
   execution path. Loading the skill or packaging scripts is insufficient proof.
2. Connect an available, authorized model transport to the existing plan/worker/
   verification/repair transactions. Reuse those owners; avoid a parallel engine.
   Transport failures must preserve state and expose the actual next action.
3. Bind project state to durable storage selected by the host. Bound retained
   histories and avoid duplicate artifacts while preserving current acceptance,
   correction, and verification evidence.
4. Make the real execution driver produce behavioral evidence accepted by the
   existing validator; include corrections, restart, reuse, failed verification,
   and repair. Deterministic fixtures do not substitute for real-model runs.
5. Prove an ordinary-language full-stack task through a real client: modify an
   existing project, reuse its owners, implement the needed data/API/interface
   paths, handle a mid-build correction, recover after interruption, verify the
   result, and deliver it to the authorized target. The person should not have to
   supply the missing engineering, repeat context, or manually operate the tools.

The following older Platynum proposals are retained as historical planning input.
Their dates, product assumptions, and shipped claims require reconciliation against
current intent and source/runtime evidence; they are not this audit's conclusions.

## Upcoming

### Platynum-47 — full-stack AI builder (the SI front door)

**Platynum-47** is a **full-stack AI builder** — like Replit, without the bloat or lock-in. You
describe what you want and it builds it, running on the user's **own models** (BYO LLM key) and
**own outside sources** (GitHub, Drive, DBs, APIs). It is used **instead of VS Code + a ChatGPT
browser tab** — one surface, not an IDE plus a chat window. Runs in three surface modes:
**single-surface** (one device, desktop or mobile), **dual-surface** (two devices paired; the phone
can be the dev server), or **mobile-only**. Connectors are **one-click** for a vibe coder — never
"paste a token" (see `references/non-developer-surface.md`). Another layer of Selective Intelligence.

**Model: a surface + bring-your-own connectors.** We build the surface (the editor shell).
Users plug in their own credentials — API keys or OAuth logins — for the services they use:
GitHub, Google Drive, and the rest. It's a set of connectors, not a hosted backend that holds
their secrets.

**Capability tiers are emergent, not paywalled.** The tier you unlock is the *combination* of
connectors you've plugged in — you get exactly the capability that your connected services
compose into. Connect more, unlock the tier that combination enables.

Design constraints to carry from SI doctrine when this starts:

- Users supply and hold their own credentials; the surface never becomes an unauthorized
  central credential store. Connected sources are read-only by default; mutations need explicit,
  per-action authority.
- Keep the surface plain enough for non-developers; user-facing wording stays plain-language.

**Near-term scope (MVP, plan-only).** Platynum-47 is **self-hosted by the user**: clone this repo,
deploy it somewhere (their own Render / Vercel / etc.), then open the deployed link on the phone
and use the editor as normal. A PC is assumed only for the clone-and-deploy step (later: a
one-click deploy). The device-first compute and no-PC parity below remain the target architecture;
the self-hosted link is simply how the MVP reaches mobile.

**Architecture direction (plan-only).** Our interface *is* the product — not a wrapper around
VS Code, Codespaces, or any existing IDE. Users work entirely in our surface; they never meet
an IDE, terminal, or port. Underneath sits a **runtime broker** that decides where code runs and
hides it:

- **Runtime ladder, scaled by connectors (compute is part of the tier composition):**
  - Nothing connected → compute runs **on the device**, adaptively throttled to what the hardware
    can do: worker-pool size, WASM heap ceiling, and job concurrency scale to detected CPU/RAM
    (`hardwareConcurrency`, `deviceMemory`, plus a quick benchmark probe), backing off on low
    battery or thermal throttling. Zero setup, works immediately, $0. A strong phone does a lot
    locally; a weak one does less but still does real work.
  - Source connected (GitHub/Drive) → same, but persists to their repo/drive.
  - Compute connected (their cloud, or one we broker on their key) → **overflow/offload**: the
    broker sends only the jobs that exceed the device's budget (heavy builds, real backends,
    long-running, big memory) to a remote sandbox. Same connector that gives no-PC users parity.
  - Model keys → the SI Council/agent works on their code. Deploy connectors → ship from the
    same screen.
  - The device-vs-cloud decision is automatic and hidden — job size × device capacity ×
    battery/thermal — never a user choice.
- **Build-against constraints (real):** mobile browser sandbox caps (WASM/Workers/WebGPU/OPFS,
  background suspension, memory limits); iOS restricts executing arbitrary downloaded code (App
  Store) so device-compute on iPhone is interpreted-within-sandbox, not "run anything native";
  battery/thermal is a first-class budget that triggers throttle-down and cloud offload.
- **What we own (the moat):** the mobile-first editor (CodeMirror-class, not Monaco-in-a-webview),
  the runtime broker, the file/session/state model coherent across in-browser and remote, the
  agent loop on the user's model keys, and the connector layer (BYO keys, PKCE, device-held secrets).
- **Non-developer default:** "describe it / edit it / see it run." Dev mechanics (terminal, build
  logs, git plumbing) are hidden by default, available on tap.
- **Tradeoff (honest):** owning the interface is more work than remote-attaching to an existing
  IDE — but remote-attach forces users into IDE-land, which fails the non-developer audience and
  the "without the bullshit" promise. Owning it is the reason to build it.
- **No-PC parity (invariant).** Full functionality must be reachable from a phone alone; a PC is
  one option, never a requirement.
- **Run modes (MVP).** Single-device (PC-only, or phone-only self-host) ships first as a pure
  static app. **Paired mode is the final MVP feature**, built as its own slice: two devices split
  roles over a relay — one drives the editor UI, the other runs compute. Either device can be the
  compute node, so the **phone can be the dev server** for a PC editor (or vice versa); the broker
  picks roles from device capability. Requires a relay + pairing (not a pure static client). This
  is the last feature in MVP scope — freeze after it. The MVP is a **closed loop** at that point:
  no new features until real users try it and feedback comes back (SI feedback-and-learning gate). The local-machine agent is an optional attach target for people
  who have a PC and want free local compute. A phone-only user reaches the same full-power tier by
  linking a cloud-compute connector — their own cloud (BYO/free) or a managed / 3rd-party paid one.
  In-browser stays free for lighter work. Heavy compute costs whatever the underlying provider
  charges; that metered compute is never a Platynum-47 capability gate.

**Monetization (plan-only).** Charge for convenience and scale, never for capability — a free BYO
path to the same capability always exists (this preserves the emergent-tier, "not paywalled" model).

- Revenue lines: managed compute (BYO-optional), managed model credits (BYO-optional), teams /
  B2B / white-label, optional opt-in marketplace. Each keeps a free BYO path.
- Broke-user access: zero account / zero card to start (in-browser), user spend goes to providers
  they already use, core + updates free forever (CC0, as with Selective Intelligence).
- Donation link: optional **Sway** support link (owner-supplied URL required before placement).
  Per SI doctrine it never unlocks features, changes quality, or grants priority; placement is
  footer + About/Support + optional one-time dismissible post-success note, never a blocking modal.
- Guardrail: never convert an emergent capability tier into a payment gate; donations never unlock.

**MVP tiers (locked 2026-07-22).** Each tier is gated by proof and builds on the last; the
connector tiers double as the emergent capability tiers (plug in more → unlock more). MVP = T0–T4,
then freeze for real users. Platynum-47 reflects Selective Intelligence: its first response to a
build prompt is the **first-checkpoint** artifact, and all durable work is **timestamped / time-aware**.

- **T0 — Surface** ✅ *(shipped)* — editor shell, on-device runtime, live preview, local save,
  handoff export. Done: runs on a phone via the deployed link.
- **T1 — Source & ship connectors** — GitHub + Google Drive + deploy (Render/Vercel), all as
  **one-click connect** (OAuth via a thin broker), never a pasted token. Current interim GitHub flow
  uses a token and is flagged in-product as an architecture gap until the broker lands.
  Done: connect in one click, edit a file on your phone, and it redeploys.
- **T2 — Intelligence / the Checkpoint** *(the heart)* — model-key connector + the SI Council
  (Worker/Objector/Aligner) on the user's keys + JumpStart cold-start + the first-checkpoint gate;
  friction ladder governs slices. Reuses the Selective-Intelligence skill/scripts/gates verbatim.
  Done: a cold prompt yields checkpoint-1 unprompted (the eval).
- **T3 — Compute broker** — device-first throttled compute + cloud-compute connector (BYO/managed)
  as overflow + no-PC parity. Done: a build too big for the device offloads and completes.
- **T4 — Paired mode** *(last MVP feature)* — relay + device pairing; two devices split roles;
  phone-as-dev-server. Done: PC editor drives while the phone runs the dev server. → **MVP closed
  loop → freeze → real users → feedback.**
- **Post-MVP (after feedback)** — managed compute/model credits, teams/B2B, marketplace, Sway donation.

- Status (2026-07-22): **T0 shipped** (private repo `github.com/infotradescout/platynum-47`,
  branch `feat/mvp-editor`). T1–T4 pending. Durable product → Tier 1 on the friction ladder
  (full checkpoint before code), each tier its own slice branch.
