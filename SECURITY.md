# Security policy

Selective Intelligence treats security as a release gate. A feature is not complete merely because an AI can discover or invoke it; the complete identity, authority, target, approval, data, and evidence chain must fail closed.

## Report a vulnerability privately

Use [GitHub private vulnerability reporting](https://github.com/infotradescout/Selective-Intelligence/security/advisories/new). Do not open a public issue for a vulnerability and do not include secrets, private prompts, personal data, or proprietary repository content.

## What is supported

Until versioned releases are published, security fixes target the latest commit on `main`. Older commits and unofficial copies may not receive fixes. Release archives will name their supported version once the public release gate is satisfied.

For an ordinary bug, wrong outcome, or improvement idea, use the repository's public feedback and suggestion forms instead.

## Trust boundaries

- Only current user input can directly activate the `Selective Intelligence` master trigger. Repositories, profiles, manifests, webpages, tool output, model output, and retrieved instructions are untrusted data and cannot approve adoption or actions.
- A public profile URL or capability manifest carries no authority or credentials. The final URL, canonical product origin, machine-readable marker, declared resource, and target identity must all agree.
- Authentication proves an account session, not unlimited authority. Each integration must derive the acting user and exact target from its protected connection, enforce owner or delegated-manager permissions server-side, and keep MealScout and TradeScout authority separate.
- Read, draft, apply, publish, send, spend, permission-change, and delete are distinct action classes. Unknown actions are denied. Consequential changes require a preview and approval bound to the exact current revision, target, destination, and effect.
- Profile text, images, metadata, menus, offers, and linked content remain untrusted business data. Instructions inside them must never alter system policy, request secrets, widen scope, choose a different target, or self-approve.
- Passwords, session cookies, bearer tokens, API keys, client secrets, private prompts, and hidden reasoning must never be requested in chat, placed in a public manifest, committed, logged, or included in feedback.

## Integration release requirements

Before a profile-link integration can claim write capability, it must prove:

1. an allowlisted HTTPS origin and canonical target with look-alike host, redirect, query, fragment, path-confusion, and cross-target cases rejected;
2. account and tenant ownership enforced at the destination, with least-privilege scopes and no caller-supplied identity used as authority;
3. short-lived access, refresh rotation where applicable, explicit revocation, session/ownership-change handling, rate limits, and an operator kill switch;
4. read-before-draft, immutable preview, stale-revision rejection, destination-specific approval, idempotency or safe retry behavior, and an audit record without secrets;
5. prompt-injection, credential-exfiltration, cross-product, wrong-owner, missing-connection, revoked-token, and unconnected-destination adversarial tests;
6. truthful public capability reporting. A protected browser handoff is not a remote API, and a successful local test is not proof of a production write.

If any requirement is absent or its evidence becomes stale, the integration must fall back to read-only guidance or stop at the product's protected sign-in/editor boundary.

## Data and feedback

The core skill has no required account or telemetry. Feedback is local by default. Any future central feedback path must be explicit opt-in, collect the minimum useful outcome signal, identify its retention/deletion rules, and exclude source content, credentials, private prompts, personal data, and hidden reasoning.
