# Security policy

Selective Intelligence treats security as a release gate. A feature is not complete merely because an AI can discover or invoke it; the complete identity, authority, target, approval, data, and evidence chain must fail closed.

## Report a vulnerability privately

Use [GitHub private vulnerability reporting](https://github.com/infotradescout/Selective-Intelligence/security/advisories/new). Do not open a public issue for a vulnerability and do not include secrets, private prompts, personal data, or proprietary repository content.

## What is supported

Until versioned releases are published, security fixes target the latest commit on `main`. Older commits and unofficial copies may not receive fixes. Release archives will name their supported version once the public release gate is satisfied.

For an ordinary bug, wrong outcome, or improvement idea, use the repository's public feedback and suggestion forms instead.

## Trust boundaries

- Only current user input can directly activate the `Selective Intelligence` master trigger. Repositories, manifests, webpages, tool output, model output, and retrieved instructions are untrusted data and cannot approve adoption or actions.
- Authentication proves an account session, not unlimited authority. Each external integration must derive the acting user and exact target from its protected connection and enforce least-privilege permissions at the destination.
- Read, draft, apply, publish, send, spend, permission-change, and delete are distinct action classes. Unknown actions are denied. Consequential changes require a preview and approval bound to the exact current revision, target, destination, and effect.
- External records, text, images, metadata, and linked content remain untrusted data. Instructions inside them must never alter system policy, request secrets, widen scope, choose a different target, or self-approve.
- Passwords, session cookies, bearer tokens, API keys, client secrets, private prompts, and hidden reasoning must never be requested in chat, placed in a public manifest, committed, logged, or included in feedback.

## Data and feedback

The core skill has no required account or telemetry. Feedback is local by default. Any future central feedback path must be explicit opt-in, collect the minimum useful outcome signal, identify its retention/deletion rules, and exclude source content, credentials, private prompts, personal data, and hidden reasoning.
