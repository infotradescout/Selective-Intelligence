# Contributing to Selective Intelligence

Selective Intelligence is open infrastructure under CC0. Contributions are welcome from product owners, designers, developers, researchers, and people who found a real failure while using an AI—not only from specialists who know the repository already.

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
python -B skills/selective-intelligence/scripts/eval.py controls --json
python -B skills/selective-intelligence/scripts/council.py self-test
python -B skills/selective-intelligence/scripts/behavior_eval.py self-test
python -B -m unittest discover -s skills/selective-intelligence/tests -p 'test_*.py'
python -B skills/selective-intelligence/scripts/release.py doctor --json
```

For a behavior change, add or update a case and attach captured fresh-context output plus independent per-invariant grading. A case identifier with a `pass` flag is not behavioral evidence. Never claim universal model or client equivalence from one model, one context, or deterministic checks alone.

## Open the contribution

Open a focused pull request against the canonical repository. Explain the failure, governing intent, changed ownership layer, proof, and remaining frontier. Keep unrelated cleanup separate so reviewers can trace the change to its evidence.

By contributing, you agree that your contribution is released under the repository's [CC0 1.0 Universal](LICENSE) dedication.
