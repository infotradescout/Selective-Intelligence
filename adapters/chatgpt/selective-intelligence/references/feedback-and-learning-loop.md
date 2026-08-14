# Privacy-Preserving Feedback and Learning Loop

Use this loop when a project needs durable, local evidence about whether work helped. It improves the next decision; it is not a user survey, employee-performance system, or a store for prompts and reasoning.

## Principles

1. Prefer inferred signals: observed validation, error, retry, correction, block, handoff, or reopened-work events. Do not interrupt a user for a rating when the outcome is observable.
2. Store JSONL locally in the project (`.selective-intelligence/feedback/events.jsonl` by default). The utility has no network behavior, creates a local ignore rule for the default store, and restricts file permissions where the operating system permits. Do not commit the event store.
3. Do not record raw prompts, model reasoning, messages, source documents, user identifiers, secrets, URLs with tokens, or free-form notes. Record only the allowlisted event fields.
4. Use a tiny manual verdict only when outcome cannot be inferred. The only values are `Worked`, `Partly`, and `Wrong`; recording one requires `--inference-insufficient`.
5. Treat a correction, failed validation, or material blocker as useful evidence—not as a reason to suppress the event. Do not use raw tool-call count, token count, or “tasks closed” as a quality metric.
6. Central aggregation is off by default. A privacy-safe aggregate export is still local; any future upload requires an explicit `--for-central-aggregation --central-aggregation-opt-in` command and separate authority for the destination.

## Compact taxonomy

Use one cause per event. Choose `unknown` rather than inventing precision.

| Field | Values |
|---|---|
| `event` | Start/tool/validation, correction or override, invalidated evidence, reopened work, recurring drift, unverified claim, question burden, false-positive gate, release closure, blocker, handoff, or fallback verdict |
| `cause` | Intent, scope, evidence, architecture, reuse/directorization, data/API/access/state/lifecycle/reachability, integration/operations, UI/UX, status, safety/privacy, continuity, portability, distribution, question burden, tooling, or `unknown` |
| inferred outcome | `worked`, `partly`, `wrong`, `blocked`, `unknown` |
| validation scope | `none`, `focused`, `integration`, `end_to_end`, `rendered`, `production` |

The utility accepts only opaque UUID task IDs. It intentionally has no customer, repository, model, prompt, or actor field.

## Commands

Run `python3 scripts/feedback.py --help` for details.

```bash
# Start a local opaque task record.
python3 scripts/feedback.py record --task-id 00000000-0000-4000-8000-000000000001 \
  --event task_started --cause unknown

# Add an observable signal.
python3 scripts/feedback.py record --task-id 00000000-0000-4000-8000-000000000001 \
  --event validation_passed --cause api_contract --validation-scope integration

# Only if there is no usable observed signal for the task.
python3 scripts/feedback.py record --task-id 00000000-0000-4000-8000-000000000002 \
  --event verdict_recorded --cause unknown --verdict Partly --inference-insufficient

python3 scripts/feedback.py doctor
python3 scripts/feedback.py summarize
python3 scripts/feedback.py export --output /tmp/feedback-aggregate.json
```

`doctor` validates JSONL, schema, opaque IDs, event vocabulary, and likely prohibited content without printing events. `summarize` reports task-level inference coverage, correction rate, validation coverage, and outcomes. It does not rank people or reward activity volume. `export` writes aggregate counts only; it never transmits data.

The summary also reports first-pass verified outcomes, rework and reopen rates, drift recurrence, false-completion signals, false-positive gates, questions per task, and recurring negative cause classes. These explain whether the workflow is functioning and where it fails without requiring a research interview.

## Metric guardrails

- Use a task-level denominator only for tasks with an opaque `task_started` event. Never report a success rate without its denominator and the count with insufficient evidence.
- Prefer the strongest observed outcome: a later validation failure or correction prevents a task from being counted as worked. A material blocker remains visible rather than being counted as success.
- Keep manual verdicts separate from inferred outcomes and exclude them whenever stronger evidence exists.
- Review cause distributions and repeated corrections for improvement opportunities; do not set targets that reward suppressing failures, avoiding validation, or creating more events.
- Promote one severe truth, safety, authority, privacy, destructive-action, or false-completion failure immediately. For ordinary behavior, wait for the same cause across independent tasks before changing the universal skill.
- Turn promoted causes into a reproducible fixture, the narrowest effective rule or validator, a clean-context forward test, and a release. Watch the recurrence rate after release; a rewritten paragraph alone is not improvement.
- Delete the local file when it no longer serves its bounded project purpose. If retention, sharing, or compliance obligations apply, record them in the project’s data and operations contract before collecting.
