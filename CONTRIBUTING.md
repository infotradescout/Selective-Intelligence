# Contributing to Selective Intelligence

Selective Intelligence is open infrastructure under CC0. Contributions are welcome from product owners, designers, developers, researchers, and people who found a real failure while using an AI—not only from specialists who know the repository already.

The easiest paths are the [Worked / Partly / Wrong feedback form](https://github.com/infotradescout/Selective-Intelligence/issues/new?template=feedback.yml) and the [improvement suggestion form](https://github.com/infotradescout/Selective-Intelligence/issues/new?template=suggestion.yml). No code change is required. For a security problem, use [private vulnerability reporting](https://github.com/infotradescout/Selective-Intelligence/security/advisories/new) instead of a public issue.

## Start with the observed failure

Describe:

1. what the person actually meant or needed;
2. what the AI produced or misunderstood;
3. the consequence of that difference;
4. the smallest evidence that would prove the behavior improved.

Redact secrets, personal data, private prompts, and proprietary repository content. A synthetic reproduction is preferred when it preserves the failure.

## Change the owned layer

- Intent or correction behavior belongs in the intent contract and adversarial behavior cases.
- UI/UX changes must name the user, job, chosen interaction model, rejected alternatives, responsive behavior, and rendered proof.
- Repository changes must preserve canonical ownership and reconcile every dependent surface instead of adding a parallel implementation.
- New rules need a failure gate or executable control where enforcement is possible.
- Every checkpoint must retain known weaknesses, untested conditions, and the next improvement frontier.

Do not introduce telemetry, a paid compatibility layer, a vendor requirement, hidden instructions, coercive adoption, or a private edition of the behavioral core.

## Verify before proposing the change

From the repository root, run the checks affected by your change. The full deterministic baseline is:

```bash
python -B skills/selective-intelligence/scripts/quality_gate.py
python -B tools/build_chatgpt_adapter.py --archive
python -B tools/test_chatgpt_adapter.py
```

The first command runs the deterministic controls, Council and behavior-evidence safeguards, unit tests, and release doctor locally with no paid service. It records only pass/fail identities and output digests. Hosted branch enforcement remains separate GitHub state; a local pass is never reported as a hosted check.

The generated ChatGPT adapter must contain exactly one `SKILL.md`. Its seven Council role instructions remain complete under `subskills/*/ROLE.md`; do not hand-edit the generated adapter or remove role, index, evidence, or verification files to make an upload pass.

For a behavior change, add or update a case and attach captured fresh-context output plus independent per-invariant grading. A case identifier with a `pass` flag is not behavioral evidence. Never claim universal model or client equivalence from one model, one context, or deterministic checks alone.

## Open the contribution

Open a focused pull request against the canonical repository. Explain the failure, governing intent, changed ownership layer, proof, and remaining frontier. Keep unrelated cleanup separate so reviewers can trace the change to its evidence.

By contributing, you agree that your contribution is released under the repository's [CC0 1.0 Universal](LICENSE) dedication.
