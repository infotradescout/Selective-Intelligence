# Start Mode: New-Project Lock

Use Start mode when a project is new, substantially blank, or being deliberately restarted. Convert the user's plain-language outcome into an authoritative, buildable product-and-system contract before project code is created. Then use that contract to control every build and reconcile the plan to reality afterward.

## Contents

- [Required result](#required-result)
- [Choose proportional rigor](#choose-proportional-rigor)
- [Define the MVP / smallest viable release](#define-the-mvp--smallest-viable-release)
- [Create the Start Pack](#create-the-start-pack)
- [Lock decisions truthfully](#lock-decisions-truthfully)
- [Assign decision authority](#assign-decision-authority)
- [Make requirements testable](#make-requirements-testable)
- [Plan complete vertical slices](#plan-complete-vertical-slices)
- [Run the three-phase build lock](#run-the-three-phase-build-lock)
- [Control amendments](#control-amendments)
- [Definition of a closed build](#definition-of-a-closed-build)
- [Close the release separately](#close-the-release-separately)
- [Start-mode gates](#start-mode-gates)
- [Handoff](#handoff)

## Required result

Produce a durable **Start Pack** that lets a different capable model or developer build the same intended product without reinventing its business rules, architecture, data ownership, interfaces, or completion standard.

Do not begin project implementation until:

- the desired outcome, primary user job, non-negotiables, prohibitions, and completion proof are Locked or Supported;
- the smallest viable release is a complete end-to-end value loop;
- every material product, architecture, data, API, access, UI, operational, and release decision is resolved or explicitly bounded;
- unresolved choices that could change the business model, user journey, security boundary, irreversible architecture, or substantial cost have been put to the authorized user in one plain-language question;
- the first build slice has an observable acceptance contract and a **Before-build locked** verdict.

“Everything defined” does not require predicting every implementation detail. It requires closing every category below, marking truly irrelevant items **Not applicable** with a reason, and preventing implementation agents from silently making material product decisions. Reversible technical details may remain implementation choices only when they cannot change a locked contract.

When the user authorizes building, do not stop at the Start Pack. Lock the first slice, execute it, reconcile it, and continue within the authorized scope.

If the project is a restart, replacement, extraction, or adjacent product, inventory inherited users, data, domains, traffic, integrations, assets, public promises, credentials, deployments, and obligations before treating the repository as greenfield.

## Choose proportional rigor

Choose the path from risk and reversibility, not project prestige:

- **Micro:** one reversible, low-risk artifact or utility with no sensitive data, shared mutable state, external side effects, public commitment, or production migration. Combine contracts into the compact Start Pack, but retain intent, scope, owner, acceptance, evidence, and truthful status.
- **Standard:** a normal product or multi-surface feature. Use the complete Start Pack and three-phase lock.
- **High assurance:** sensitive data, multi-tenant access, public mutation, payments or entitlements, AI autonomy, destructive migrations, regulated domains, or meaningful production risk. Use the complete pack, operational safety gates, machine validation, and independent review.

Escalate the profile when new evidence crosses a trigger. Never use Micro to evade a material unknown or safety obligation. Never force a throwaway one-file experiment through enterprise ceremony when its boundary and disposal are explicit.

## Define the MVP / smallest viable release

Define the smallest viable release as the smallest complete, credible loop in which the primary user can reach the promised outcome in the intended environment. Optimize for learning and usefulness by removing adjacent jobs, not by hollowing out the core job.

Use **MVP** only as shorthand for this standard. Never let it mean an attractive shell, a pile of disconnected features, or the smallest amount of code an agent can produce.

Use this removal test: if removing an item still lets the primary user reach the primary value event safely, truthfully, and operably, the item is not part of the smallest viable release unless it is a mandatory security, legal, reliability, migration, or release constraint.

The release normally includes, when the outcome requires them:

- a reachable entry point and understandable first action;
- real state, data ownership, persistence, and lifecycle behavior;
- the required identity, authorization, privacy, and abuse boundaries;
- the frontend, backend, database, and external integration path working together;
- loading, empty, error, retry, success, and recovery states;
- truthful measurement and evidence of the primary outcome;
- a deployable environment, configuration contract, and rollback path.

Include every human or system actor required to deliver the value, not only the person pressing the first button. A submission is not a viable marketplace, fulfillment, support, moderation, notification, or commercial loop when the receiving actor cannot complete their part.

Do not label a screen-only shell, mocked critical backend, orphaned schema, unconnected API, manual operator substitution, or fake payment/data flow a viable release unless the user's authoritative intent is explicitly to build a disposable prototype. Name prototypes as prototypes and keep their evidence separate from product completion.

## Create the Start Pack

Persist the Start Pack under `.selective-intelligence/` so it remains discoverable and portable across models and tools. If the project already has an authoritative governance system, integrate with it rather than creating competing truth, but retain one `.selective-intelligence/lock.json` manifest that points to the canonical artifacts. Read [tool-interoperability.md](tool-interoperability.md).

Use this default structure, combining only when the project is genuinely small and the lock manifest keeps ownership unambiguous:

```text
.selective-intelligence/
  lock.json
  intent-contract.md
  scope-release.md
  experience-surfaces.md
  architecture-contract.md
  data-contract.md
  api-integrations.md
  security-operations.md
  delivery-map.md
  traceability.md
  decisions-changes.md
  builds/<build-id>/contract.md
  builds/<build-id>/evidence.md
```

`lock.json` records the schema version, project profile, release and active build, decision owners, verdicts, requirements, build dependencies, claimed canonical owners, source and lock versions, blockers, external-fact freshness, invalidated requirements, risk triggers, artifact versions, and digests. A changed locked artifact without a corresponding authorized amendment invalidates the affected lock. Never silently rewrite a closed build's evidence.

Use the bundled dependency-free control when Python is available:

```text
python3 <skill-path>/scripts/start_pack.py init --root <project> --project-id <id> --project-name <name> --release-id <id>
python3 <skill-path>/scripts/start_pack.py doctor --root <project>
python3 <skill-path>/scripts/start_pack.py validate --root <project>
python3 <skill-path>/scripts/start_pack.py diff --root <project>
python3 <skill-path>/scripts/start_pack.py converge --root <project>
python3 <skill-path>/scripts/start_pack.py seal --root <project> --transition definition
# Later controlled seals use --transition build, --transition as-built, and --transition release in order.
# During an active Build phase, persist status and active evidence without changing product meaning:
python3 <skill-path>/scripts/start_pack.py seal --root <project> --checkpoint
python3 <skill-path>/scripts/start_pack.py status --root <project>
python3 <skill-path>/scripts/start_pack.py resume --root <project>
```

Phase transitions are non-repeatable: Definition follows an unlocked or amended baseline, Build follows Definition or As-Built, As-Built follows Build, and Release follows As-Built. A repeated phase cannot be used to absorb drift. Use an authorized amendment for semantic change. Use `--checkpoint` only inside an active Build phase to preserve legal `locked`, `in_progress`, and `interrupted` status moves plus the active build's evidence; it retains the same phase, build, lock version, and semantic digest and cannot reconcile a build or close a release. Checkpoints may add evidence invalidations but never erase them. Clearing an invalidation requires updated active-build evidence and a Reconciled As-Built transition. Material blockers are semantic controls and require amendment rather than checkpoint rewriting.

The validator checks allowed verdicts, required artifacts, safe paths, control and semantic digests, per-seal artifact ledgers, links, IDs, build dependencies, overlapping active owners and requirements, requirement coverage, ordered Definition → Build → As-Built → Release transitions, stale facts, risk triggers, invalidated evidence, and release closure. A Start Pack not checked by the validator or an equivalent implementation is **structurally unverified**, never machine-locked. If execution is unavailable, continue manually and name that limitation rather than lowering the contract.

Keep one canonical source for each decision and never create competing plans.

Every Start Pack must close these contracts:

| Contract | Required contents |
|---|---|
| Actual Intent Lock | Outcome, primary user and job, reason, authority, non-negotiables, prohibitions, tradeoffs, scope boundary, completion proof, confidence |
| Product and Scope | Actors, use cases, smallest viable release, included/deferred/excluded capabilities, dependencies, assumptions, acceptance evidence |
| Decision Classes and Authority | Product invariants, release commitments, hypotheses, reversible implementation choices, deferred decisions, decision owner, escalation rule |
| Journeys and States | Entry triggers, happy paths, failure and recovery paths, state machines, lifecycle endings, actor handoffs, notification points |
| Surfaces and Reachability | Route/page/screen inventory, role exposure, navigation and deep links, actions, public/private boundaries, loading/empty/error/success states |
| System Architecture | Runtime components, deployment topology, data flow, trust boundaries, dependency direction, background work, external services, failure boundaries |
| Canonical Ownership | Feature and module boundaries, deliberate directories, public interfaces, shared primitives, registries, ownership, reuse and extension rules |
| Data Contract | Entities, relationships, field types, required/null rules, keys, uniqueness, constraints, indexes, ownership, lifecycle, retention/deletion, migrations, seed strategy |
| API and Integration Contract | Appropriate internal and external APIs, methods/events, owners and consumers, request/response schemas, auth, errors, idempotency, retries, timeouts, rate limits, versioning, webhooks, cost and provider limits |
| Access and Safety | Roles, permission matrix, tenant or resource isolation, secrets, personal/sensitive data, audit events, moderation/abuse controls, backup and recovery |
| UI/UX Contract | Information architecture, design direction and tokens, canonical primitives, content hierarchy, interaction states, responsive targets, accessibility, copy/action/route agreement |
| Operations and Measurement | Environments, configuration, observability, logs/metrics/traces as appropriate, analytics events, outcome metrics, deployment, rollback, support and incident ownership |
| Verification and Release | Test layers, realistic fixtures, contract and migration checks, rendered UI inspection, end-to-end journeys, security checks, release gate, live verification plan |
| Delivery Plan | Dependency-ordered vertical slices, acceptance contract per slice, risks, decision owners, change process, build and reconciliation status |
| Decision and Evidence Ledger | Decision, status, authority, rationale, affected contracts, evidence, version, date, superseded decision, open conflicts |
| Product-to-Code Coverage | Each capability tracked through Intended, Specified, Modeled, Implemented, Wired, Reachable, Usable, Verified, and Live |
| Feedback and Learning | Run outcome, correction and recurrence signals, gate effectiveness, minimal user verdict when needed, privacy-safe improvement evidence |

For current external APIs, inspect authoritative current documentation rather than relying on recalled names or behavior. Record why the API is appropriate, the capability and version used, authentication, plan and region, observed date, revalidation date or trigger, limits, costs that affect architecture, data handling, failure behavior, and an exit or degradation path where material. Expired evidence becomes Provisional or Unverified. Do not choose a vendor merely because a model recognizes it.

For data and API definitions, use concrete schemas, examples, and state transitions. A list of nouns or endpoint names is not a contract. For UI/UX, define the whole journey and its non-happy states; a wireframe or component list alone is not a product experience.

Run the trigger pass in [operational-safety-gates.md](operational-safety-gates.md). Generic headings do not satisfy a triggered safety contract.

## Lock decisions truthfully

Use these statuses:

- **Locked:** directly authorized or formally approved and ready to govern implementation.
- **Supported:** consistently established by authoritative context and safe to govern implementation.
- **Provisional:** reversible working choice awaiting authority; cannot govern an expensive or architecture-changing commitment.
- **Conflicted:** authoritative inputs disagree; blocks affected work.
- **Unknown:** evidence is insufficient; blocks affected work when material.
- **Not applicable:** category was evaluated and does not apply, with a reason.
- **Superseded:** replaced by a newer authorized decision while retained for traceability.

Give each lock a version and record who or what supplied its authority. Locking does not mean the project can never change. It means a material change must be deliberate, impact-aware, authorized, versioned, and propagated to every affected contract before implementation proceeds.

Map the whole product and its end-state architecture, but lock implementation detail only for the current smallest viable release and active build. Later releases may remain Provisional; material decisions for the active release may not. Do not create an implicit “maybe” scope.

Documents do not become authoritative because they exist. Resolve conflicts using the intent authority map, and never convert agent-authored guesses into Locked decisions.

## Assign decision authority

Decision class and evidence status are separate. Classify each material decision as:

- **Product invariant:** authoritative product behavior or doctrine that remains governing within its stated scope.
- **Active-release commitment:** a bounded product or technical choice required for the current release; it does not become permanent doctrine by repetition.
- **Testable hypothesis:** an expectation about users, value, demand, scale, or implementation that needs a validation signal, decision deadline or trigger, and reversal path. Plausibility cannot make it Locked or Supported fact.
- **Reversible implementation choice:** a technical choice the implementing agent may make inside all locked boundaries; record it only when later work depends on it.
- **Deferred decision:** a choice with a named decision owner and decide-by condition that is not a dependency of included work.

Product promises, business rules, public behavior, authority, and material tradeoffs require product authority. Technical owners may decide bounded implementation details. Legal or regulated interpretations, credentials, payments, acceptance of terms, and irreversible external actions require their accountable authority; evidence can inform authority but cannot create it. Apply [actual-intent-alignment.md](actual-intent-alignment.md).

Lock only the narrowest commitment needed now. Keep speculative future scale, market behavior, and later-release architecture Provisional. A **Not applicable** or **Deferred** label must state why and cannot hide a dependency of an included requirement. When several unknowns descend from one product fork, ask one root product question and derive the technical consequences instead of serially questioning the user.

## Make requirements testable

Define every included requirement independently of the planned code. State its actor, precondition or trigger, observable behavior and ending, relevant constraint, prohibited or negative case, environment or data boundary, canonical owner, and proof.

An acceptance criterion must fail when the wrong route renders, the real consumer is disconnected, a critical dependency is mocked, state does not persist, an unauthorized actor succeeds, or the promised external effect does not occur. Strings, comments, filenames, source existence, broad containers, implementation-shaped mocks, and the implementation's own assertions are not independent oracles. Apply the self-fulfilling-test gate in [failure-patterns-and-gates.md](failure-patterns-and-gates.md).

Assign every MVP and mandatory requirement to a build before Definition Lock. If an outcome cannot yet be observed or tested truthfully, keep it as a discovery question or hypothesis rather than weakening its acceptance criterion.

## Plan complete vertical slices

Order work by dependencies and user value. Prefer slices that connect the necessary UI, behavior, data, access, and evidence for one observable user outcome. Avoid separate “build all pages,” “build all APIs,” and “build all database tables” phases that postpone integration until the end.

For each slice, define:

- user outcome and governing intent rule;
- included and prohibited behavior;
- entry, action, state transition, and observable ending;
- canonical feature/module owners and directories;
- reuse, extend, extract, consolidate, create, or remove decisions;
- data, migration, API, event, UI, access, and operational changes;
- dependency and environment prerequisites;
- realistic acceptance cases, negative cases, and evidence;
- rollback or safe-disable approach when relevant;
- highest feature state the slice is expected to reach.

Do not place a slice in the build queue when its material dependency or governing lock is Conflicted or Unknown.

## Run the three-phase build lock

Read [continuity-and-impact.md](continuity-and-impact.md) whenever work spans builds, agents, branches, worktrees, repositories, interrupted runs, or external control planes.

### 1. Definition Lock (before-build)

Create or refresh the slice contract. Trace it from authoritative intent to requirement, planned implementation surfaces, and acceptance evidence. Confirm canonical ownership and the reuse disposition before new code. Compare the slice against included, deferred, and prohibited scope.

Record the source base revision, lock version, included requirement IDs, claimed canonical owners, build dependencies, and required merge order. An active build with an unresolved base or an unapproved ownership overlap is Blocked.

Give every included requirement a stable ID. Each included requirement must have an observable acceptance criterion, journey, canonical owner, data or API dependency where applicable, and planned proof. Every planned table, endpoint, event, service, module, page, and component must trace to one of those requirements or a mandatory operational constraint.

Seal the current artifacts, then run `start_pack.py validate` or an equivalent deterministic validator before granting the lock. Every manifest path, local link, requirement ID, build ID, version reference, artifact digest, verdict transition, and cross-artifact trace must resolve to the intended target and agree with its canonical record. Structural validation is necessary but does not prove product correctness.

Run an adversarial review separate from the author when that capability exists. It is required for High assurance work, triggered safety contracts, and materially irreversible decisions. The reviewer must attack unsupported authority, omitted actors or states, `Not applicable` and Deferred classifications, self-fulfilling acceptance, unsafe rollback, and parallel-owner conflicts using source evidence rather than the packet's conclusions. Register the review evidence as a digested Start Pack artifact and record a reviewer distinct from the declared decision owners, review timestamp, scope, and exact revision. A truthy label or self-authored summary is not independent review, and review cannot manufacture missing authority.

A time-boxed, isolated discovery spike may resolve a material unknown. Mark it as discovery, keep it outside production paths, and do not use its existence as completion evidence.

Verdict:

- **Before-build locked:** material decisions and dependencies are ready; implementation may begin.
- **Blocked:** name the exact unresolved product decision, dependency, authority, or access need; do not let the implementation model invent it.

### 2. Build Lock (during-build)

Implement only the locked slice and preserve its contracts. Keep the coverage map current. Search before creating, register every new surface, and keep feature code inside its canonical owner.

Do not continue from an unrecorded or stale base. A merge, rebase, lock-version change, upstream contract change, or newly overlapping owner requires refresh, validation, impact analysis, and re-lock before affected work continues. Independently passing parallel builds are not integration evidence.

When evidence reveals a material mismatch, pause the affected path and use amendment control. Do not silently change scope, user behavior, data ownership, schema meaning, API contracts, trust boundaries, pricing, provider commitments, or completion criteria. Reversible implementation details that remain inside all locked boundaries may be decided locally and recorded when they affect future work.

Classify each discovery as:

1. **Defect or clarification:** preserves the lock; record it and proceed.
2. **Mandatory dependency, safety, or correctness work:** amend affected artifacts and re-lock before proceeding.
3. **Enhancement or new idea:** defer by default outside the active release or build.
4. **Material product, scope, architecture, data, access, or public-contract change:** stop the affected work, complete impact analysis, obtain the required authority, version every affected artifact, and re-lock.

Verdict:

- **Build aligned:** work remains inside the current lock.
- **Amendment required:** discovered reality would change a locked contract.
- **Blocked:** safe aligned implementation cannot continue.

### 3. Evidence / As-Built Lock (after-build reconciliation)

Inspect the actual implementation and user path. Compare planned versus actual routes, modules, dependencies, schemas, migrations, API behavior, permissions, UI states, configuration, tests, and operational evidence. Update the Start Pack to observed truth; do not preserve aspirational status.

For each evidence item, record the requirement ID, source revision or build digest, lock version, environment and material configuration, actor or role, representative fixture or data, exact check or observation, expected and actual result, timestamp, verdict, and limitations. Evidence without enough identity to reproduce or attribute it cannot close a requirement.

Compute transitive impact from every changed owner, schema, API, route, permission, shared primitive, configuration, event, job, dependency, and external fact. Mark affected prior requirements invalidated, lower them to the highest state still proved, and reverify or reopen them before reconciliation. Do not rerun only the newest slice's tests when shared behavior changed.

Skipped, quarantined, expected-failing, or flaky checks cannot support closure. A green retry does not repair unreliable evidence; fix the instability or replace it with a reliable proof.

Run drift searches for duplicates, orphaned modules, unregistered routes, stale names, bypassed primitives, undocumented contracts, and accidental scope. Validate through the real boundary: rendered and interactive for UI, migrated and queried for data, invoked for APIs, and deployed or externally observed only when claiming Live.

Verdict:

- **Reconciled and locked:** the implementation, contracts, evidence, and status maps agree; this becomes the next baseline.
- **Partially reconciled:** completed behavior is named and remaining gaps stay open; the slice is not represented as closed.
- **Not aligned:** observed behavior contradicts the lock or a prohibition.
- **Unverifiable:** required evidence could not be obtained.

## Control amendments

Before a material amendment is implemented, record:

1. the evidence or authorized instruction that triggered it;
2. the exact locked decisions and slices affected;
3. viable alternatives and their user, architecture, data, security, schedule, and cost impact;
4. the recommended change in plain product language;
5. the required authority and resulting new version;
6. the migrations, compatibility work, tests, documentation, and rollback changes it creates.

Bind the amendment's declared authority to a decision owner preserved in the prior sealed baseline, and register a digested approval-evidence artifact. This is an auditable binding, not identity authentication: higher-assurance work still needs the destination's real approval or signature mechanism.

Classify the observable semantic delta as **Added**, **Modified**, **Removed**, **Renamed**, and **Unchanged and protected**. Record affected actors, requirements, data, APIs, routes, access, configuration, migrations, compatibility, tests, and evidence. A bug fix must name both the corrected behavior and the required behavior it must not erase. Requirement IDs may be Superseded or authoritatively removed but must not silently disappear.

Propagate an accepted amendment across intent, scope, journeys, architecture, data, APIs, surfaces, security, delivery, tests, and coverage wherever affected. Mark old decisions Superseded, compute transitive evidence invalidation, reseal through the amendment, validate, and re-lock. Reject drive-by updates that change one document or code path while leaving the system contract split. See [continuity-and-impact.md](continuity-and-impact.md).

## Definition of a closed build

A build is closed only when:

- its observable user outcome works through the intended entry and role;
- planned frontend, backend, data, access, and integration parts are connected;
- migrations and operational configuration are accounted for;
- loading, empty, error, retry, success, and recovery behavior required by the slice are usable;
- realistic positive, negative, and regression evidence passes;
- evidence is bound to the exact source, lock, environment, actor, data, and result;
- relevant UI has been rendered and inspected;
- no unexplained duplicate, orphan, stale route, or parallel implementation remains;
- no affected requirement remains invalidated and no required proof is skipped, quarantined, or flaky;
- planned-versus-actual differences are reconciled or accepted through amendment control;
- the Start Pack and product-to-code coverage report the highest evidenced state truthfully;
- all lock-manifest paths, links, IDs, versions, digests, and traceability references resolve and agree;
- the current sealed baseline passes machine validation and any required independent review;
- the next baseline receives an After-build reconciliation verdict.

Freeze the closed build's contract and evidence versions. Promote accepted corrections into the next baseline through the decision ledger instead of rewriting history.

Local compilation, source-existence checks, generated schemas, passing mocked tests, or a polished screenshot cannot close the build by themselves.

## Close the release separately

Closed builds do not equal a closed release, and an empty build queue is not completion evidence. Run release-wide reconciliation across the full included scope after the final planned slice and whenever shared behavior invalidates prior proof.

A release is **Closed** only when every MVP and mandatory requirement is assigned, reconciled, and Verified or Live at the claimed environment; every required actor and critical journey completes; protected prohibitions remain absent; triggered operational and safety contracts pass; cross-build integration, migrations, configuration, and external state agree; no included dependency is hidden as Deferred or Not applicable; no material blocker, stale fact, invalidated requirement, or flaky proof remains; and the sealed Start Pack passes validation plus required independent review. Claim Live only after observing the deployed version through its real target path.

Use **Partial** when named release requirements remain open, **Blocked** when a material decision, authority, dependency, or safety gate prevents safe completion, and **Unverifiable** when required evidence cannot be obtained. Never convert those verdicts to Closed by shrinking acceptance criteria or removing requirements without an authorized amendment. Apply the release protocol in [continuity-and-impact.md](continuity-and-impact.md).

## Start-mode gates

Block or correct these failures:

- **Architecture by accumulation:** implementation starts with no canonical owners or dependency rules.
- **Fake smallest release:** critical parts of the primary loop are mocked, manual, unreachable, or deferred while the release is called viable.
- **Plan theater:** diagrams and tables exist but lack concrete schemas, state transitions, consumers, acceptance evidence, or authority.
- **Agent-authored authority:** an inferred business rule, scope choice, provider, or trust decision is silently marked Locked.
- **Premature certainty:** a hypothesis, speculative scale assumption, future architecture, or reversible implementation choice is frozen as doctrine.
- **Applicability laundering:** hard or risky work is labeled Deferred or Not applicable even though included behavior depends on it.
- **Structural self-certification:** a model grants Definition Lock without a sealed validator pass or required adversarial review.
- **Layer-first delivery:** disconnected UI, API, and data phases postpone end-to-end truth.
- **Mid-build product invention:** implementation changes material behavior without amendment control.
- **Silent semantic erosion:** a repair passes by removing, renaming, or weakening protected behavior without an amendment.
- **API by recognition:** a familiar provider is chosen without current capability, policy, cost, failure, and data-boundary evidence.
- **Directory drift:** features, modules, components, schemas, or tests lack a deliberate canonical home or recreate shared responsibility.
- **Contract fragmentation:** code, database, APIs, UI copy, tests, and docs describe different products.
- **Stale-base parallel drift:** concurrent builds overlap owners or merge from superseded source and lock versions without refresh and integration proof.
- **Broken control graph:** artifact paths, requirement IDs, versions, digests, or cross-references are missing, stale, or point to the wrong build.
- **Evidence orphaning:** a shared change invalidates prior proof but the affected requirement keeps its Verified or Live state.
- **Flaky-green closure:** a retry, skipped check, quarantine, or nondeterministic pass is used as completion evidence.
- **Post-build fiction:** the Start Pack retains planned or Live status not supported by observed implementation.
- **Build-to-release inflation:** completed slices or an empty queue are presented as a completed release without release-wide reconciliation.
- **Model-memory dependence:** a future model must rely on conversation history or guesswork instead of the persisted contract.

## Handoff

Lead with the lock verdict and the user outcome now governed or completed. Name the Start Pack location, the smallest viable release, the current slice and feature state, validation evidence, material blocked decisions, and the next authorized build action.

Capture the smallest privacy-safe observable signal defined in [feedback-and-learning-loop.md](feedback-and-learning-loop.md): validation, correction, override, reopened work, recurring drift, invalidated evidence, false completion, question burden, gate behavior, or release closure. If the outcome genuinely cannot be inferred, ask only **Worked**, **Partly**, or **Wrong**. Silence is not approval, and one successful slice is not release acceptance. A correction reopens affected requirements, triggers sibling-failure search through [correction-harvesting.md](correction-harvesting.md), and updates reusable gate evidence after the immediate outcome is fixed. Do not ask the user to perform QA the agent can complete first.

Do not overwhelm a vibe coder with internal file inventories. Explain product decisions in plain language while keeping the complete technical contract available to the agents and developers who execute it.
