# Evidence and Completion Model

Use this reference when the output contains public factual claims, identity information, sensitive fields, or conflicting sources.

## Evidence ledger

| Class | Meaning | Allowed use |
|---|---|---|
| Confirmed | Directly supported by a reliable source | State plainly and record provenance when possible |
| Inferred | Strongly suggested but not explicit | Use only when low-risk; qualify or keep internal |
| Created | Original organization, styling, or non-factual language | Use freely when consistent with the target |
| Unknown | No adequate support | Omit, leave internally unresolved, or ask if blocking |
| Conflicted | Credible sources disagree or appear stale | Resolve with a stronger source or disclose the conflict |

Store enough provenance to revisit material claims: source URL or file, retrieval context, and relevant date. For software proof, also bind evidence to the exact source revision or build artifact, environment, configuration, role, data fixture, timestamp, expected result, actual result, and relevant dependency versions. Flaky, skipped, quarantined, stale, or fixture-only checks cannot close a requirement.

## Source weighting

Weight sources by authority, recency, specificity, internal consistency, and proximity to the subject. A first-party page is usually stronger than a directory, but an obviously abandoned first-party page may be weaker than a recent verified record. Do not resolve conflicts through source count alone.

## Safe inference test

Use an inference only if all are true:

1. It is supported by multiple consistent signals or one highly authoritative signal.
2. Being wrong would not create material harm, deception, or an unwanted commitment.
3. It improves the result more than neutral wording or omission.
4. It can be corrected without destructive consequences.

Never infer passwords, consent, ownership, legal status, professional credentials, prices, guarantees, availability, audience size, affiliations, health facts, financial facts, or acceptance of terms.

## Creative completion versus factual invention

Creative completion supplies what the agent owns: information architecture, hierarchy, summaries, transitions, layouts, formatting, interaction patterns, and original non-factual copy.

Factual invention supplies what only evidence or the subject can own: history, achievements, relationships, credentials, offerings, policies, commitments, and performance claims.

The first is required for completeness. The second is prohibited.

## Conflict handling

When sources conflict:

1. Prefer the source with greater authority and recency.
2. Check whether the conflict reflects changed state rather than an error.
3. Avoid combining incompatible details into a synthetic claim.
4. Preserve the conflict internally when it matters.
5. Ask the user only if the conflict changes the public result or required action.

External facts with changeable plans, regions, prices, policies, limits, authentication, versions, or provider behavior need an observed date and a revalidation date or trigger. Expired evidence becomes Provisional or Unverified even when the file containing it has not changed.

## Public-asset handling

- Prefer assets supplied by the user or published by the subject for the intended public use.
- Do not imply ownership or licensing merely because an asset is publicly reachable.
- Do not replace a real person, product, location, or inventory item with generated imagery without clear disclosure and user intent.
- Preserve aspect ratio and recognizable identity; do not make silent manipulations that change factual meaning.

## Completion threshold

A result is complete when it performs its intended job without placeholders or invented claims, even if optional information remains unknown. Completeness is measured by usefulness and function, not by filling every possible field.

Closed builds do not imply a closed release. Release completion additionally requires every included requirement, critical journey, prohibition, necessary actor, operational gate, and invalidated prior proof to reconcile at the current baseline.

**Cross-runtime equivalence:** Given the same task, context, and evidence, completion means an equivalently correct user outcome across models and environments—not merely fluent prose from the current runtime. Different wording is fine; different intent, scope, product truth, workflow, quality threshold, or final outcome is not. A runtime that cannot meet the bar must be corrected, retried, or blocked before side effects land. See [model-neutral-execution.md](model-neutral-execution.md#governing-requirement-model-interchangeability). One strong benchmark demonstrates that the quality bar is achievable; repeating that bar without heavy user repair is what counts as reliability.

## Council provenance

Every material Council result links its packet, role/run, provider/surface, source or artifact IDs, exact revision, validation performed, objections and dispositions, approvals, corrections, and current status. Prefer references plus hashes over copying full connected documents. Preserve license or reuse authority when adopting external material.

A local append-only hash chain can detect ordinary corruption but does not authenticate the actor or make a ledger immutable against its owner. Do not store secrets, raw prompts, hidden reasoning, or unnecessary personal data as provenance. A result cannot advance beyond the highest state evidenced at its exact revision.
