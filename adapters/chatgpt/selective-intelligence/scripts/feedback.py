#!/usr/bin/env python3
"""Local, privacy-preserving feedback evidence utility.

The tool stores only a fixed event schema in local JSONL. It deliberately has
no networking, free-form notes, prompt fields, or user/project identifiers.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import os
import re
import sys
import uuid
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
DEFAULT_STORE = Path(".selective-intelligence/feedback/events.jsonl")
EVENTS = {
    "task_started",
    "tool_succeeded",
    "tool_failed",
    "validation_passed",
    "validation_failed",
    "user_correction",
    "user_override",
    "material_blocker",
    "evidence_invalidated",
    "work_reopened",
    "drift_recurred",
    "unverified_claim",
    "question_asked",
    "gate_false_positive",
    "release_closed",
    "handoff_completed",
    "verdict_recorded",
}
CAUSES = {
    "intent",
    "scope",
    "evidence",
    "architecture",
    "reuse",
    "directorization",
    "data_contract",
    "api_contract",
    "access",
    "state",
    "lifecycle",
    "reachability",
    "integration",
    "operations",
    "ui_ux",
    "status_claim",
    "safety_privacy",
    "continuity",
    "model_portability",
    "distribution",
    "question_burden",
    "tooling",
    "unknown",
}
VALIDATION_SCOPES = {
    "none",
    "focused",
    "integration",
    "end_to_end",
    "rendered",
    "production",
}
VERDICTS = {"Worked", "Partly", "Wrong"}
ALLOWED_KEYS = {
    "schema_version",
    "event_id",
    "occurred_at",
    "task_id",
    "event",
    "cause",
    "validation_scope",
    "attempt_count",
    "source",
    "verdict",
}
INFERENCE_EVENTS = {
    "validation_passed",
    "validation_failed",
    "user_correction",
    "user_override",
    "material_blocker",
    "evidence_invalidated",
    "work_reopened",
    "drift_recurred",
    "unverified_claim",
    "gate_false_positive",
    "release_closed",
}
NEGATIVE_EVENTS = {
    "validation_failed",
    "user_correction",
    "user_override",
    "material_blocker",
    "evidence_invalidated",
    "work_reopened",
    "drift_recurred",
    "unverified_claim",
    "gate_false_positive",
}
SUSPICIOUS_PATTERNS = (
    re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I),
    re.compile(r"(?:api[_-]?key|secret|token|password|authorization)\s*[:=]", re.I),
    re.compile(r"\b(?:\+?\d[\d(). -]{7,}\d)\b"),
)


def parse_uuid(value: str) -> str:
    try:
        identifier = uuid.UUID(value)
    except (ValueError, AttributeError) as error:
        raise argparse.ArgumentTypeError("task IDs must be opaque UUIDv4 values") from error
    if identifier.version != 4 or identifier.variant != uuid.RFC_4122:
        raise argparse.ArgumentTypeError("task IDs must be opaque UUIDv4 values")
    return str(identifier)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def default_store(value: str | None) -> Path:
    return Path(value) if value else DEFAULT_STORE


def has_symlink_component(path: Path) -> bool:
    absolute = path.absolute()
    cursor = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        cursor = cursor / part
        if cursor.is_symlink():
            return True
    return False


def protect_local_store(store: Path) -> None:
    store.parent.mkdir(parents=True, exist_ok=True)
    managed_feedback_directory = (
        store.name == "events.jsonl"
        and store.parent.name == "feedback"
        and store.parent.parent.name == ".selective-intelligence"
    )
    if managed_feedback_directory:
        try:
            store.parent.chmod(0o700)
        except OSError:
            pass
        ignore = store.parent / ".gitignore"
        if not ignore.exists():
            ignore.write_text("*\n!.gitignore\n", encoding="utf-8")


def read_events(store: Path) -> tuple[list[dict[str, Any]], list[str]]:
    if has_symlink_component(store):
        return [], ["feedback store path may not contain symlinks"]
    if not store.exists():
        return [], []
    events: list[dict[str, Any]] = []
    errors: list[str] = []
    with store.open("r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                errors.append(f"line {number}: blank lines are not allowed")
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                errors.append(f"line {number}: invalid JSON")
                continue
            issue = validate_event(event)
            if issue:
                errors.append(f"line {number}: {issue}")
            else:
                events.append(event)
    return events, errors


def has_suspicious_content(event: dict[str, Any]) -> bool:
    return any(
        pattern.search(value)
        for pattern in SUSPICIOUS_PATTERNS
        for key, value in event.items()
        if key not in {"event_id", "task_id", "occurred_at"}
        if isinstance(value, str)
    )


def validate_event(event: Any) -> str | None:
    if not isinstance(event, dict):
        return "event must be an object"
    extras = set(event) - ALLOWED_KEYS
    if extras:
        return "prohibited or unknown fields: " + ", ".join(sorted(extras))
    required = {"schema_version", "event_id", "occurred_at", "task_id", "event", "cause", "validation_scope", "attempt_count", "source"}
    if not required.issubset(event):
        return "missing required allowlisted fields"
    if event["schema_version"] != SCHEMA_VERSION:
        return "unsupported schema version"
    try:
        event_id = uuid.UUID(event["event_id"])
        task_id = uuid.UUID(event["task_id"])
    except (ValueError, TypeError, AttributeError):
        return "event_id and task_id must be UUIDv4 values"
    if event_id.version != 4 or task_id.version != 4 or event_id.variant != uuid.RFC_4122 or task_id.variant != uuid.RFC_4122:
        return "event_id and task_id must be opaque UUIDv4 values"
    try:
        occurred = dt.datetime.fromisoformat(event["occurred_at"].replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        return "occurred_at must be an ISO-8601 datetime"
    if occurred.tzinfo is None:
        return "occurred_at must include a timezone"
    if event["event"] not in EVENTS or event["cause"] not in CAUSES:
        return "unknown event or cause"
    if event["validation_scope"] not in VALIDATION_SCOPES:
        return "unknown validation scope"
    if not isinstance(event["attempt_count"], int) or not 0 <= event["attempt_count"] <= 1000:
        return "attempt_count must be an integer between 0 and 1000"
    if event["source"] not in {"inferred", "user_verdict", "system"}:
        return "unknown event source"
    if event["event"] == "verdict_recorded":
        if event.get("verdict") not in VERDICTS or event["source"] != "user_verdict":
            return "manual verdict must be Worked, Partly, or Wrong from user_verdict"
    elif "verdict" in event:
        return "verdict is allowed only for verdict_recorded"
    if has_suspicious_content(event):
        return "likely PII or secret-like content detected"
    return None


def infer_outcome(events: list[dict[str, Any]]) -> tuple[str, bool]:
    names = {event["event"] for event in events}
    # Negative evidence wins so activity cannot game a success rate.
    if names & {"validation_failed", "user_correction", "drift_recurred", "unverified_claim"}:
        return "wrong", True
    if "material_blocker" in names:
        return "blocked", True
    if names & {"user_override", "evidence_invalidated", "work_reopened", "gate_false_positive"}:
        return "partly", True
    if names & {"validation_passed", "release_closed"}:
        return "worked", True
    if any(event["event"] == "verdict_recorded" for event in events):
        verdict = next(event["verdict"] for event in reversed(events) if event["event"] == "verdict_recorded")
        return {"Worked": "worked", "Partly": "partly", "Wrong": "wrong"}[verdict], False
    return "unknown", False


def command_record(args: argparse.Namespace) -> int:
    store = default_store(args.store)
    if has_symlink_component(store):
        print("refusing to use a symlinked feedback store", file=sys.stderr)
        return 2
    existing, errors = read_events(store)
    if errors:
        print("refusing to append to an invalid event store; run doctor first", file=sys.stderr)
        return 2
    task_events = [event for event in existing if event["task_id"] == args.task_id]
    if args.event == "task_started" and task_events:
        print("task_started must be the first and only start event for a task", file=sys.stderr)
        return 2
    if args.event != "task_started" and not any(event["event"] == "task_started" for event in task_events):
        print("record task_started before outcome signals", file=sys.stderr)
        return 2
    if args.event == "verdict_recorded":
        if not args.inference_insufficient:
            print("manual verdict requires --inference-insufficient", file=sys.stderr)
            return 2
        if any(event["event"] in INFERENCE_EVENTS for event in task_events):
            print("outcome is inferable for this task; do not record a manual verdict", file=sys.stderr)
            return 2
    elif args.verdict or args.inference_insufficient:
        print("--verdict and --inference-insufficient apply only to verdict_recorded", file=sys.stderr)
        return 2

    event: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "event_id": str(uuid.uuid4()),
        "occurred_at": utc_now(),
        "task_id": args.task_id,
        "event": args.event,
        "cause": args.cause,
        "validation_scope": args.validation_scope,
        "attempt_count": args.attempt_count,
        "source": "user_verdict" if args.event == "verdict_recorded" else args.source,
    }
    if args.event == "verdict_recorded":
        event["verdict"] = args.verdict
    issue = validate_event(event)
    if issue:
        print(f"refusing unsafe event: {issue}", file=sys.stderr)
        return 2
    protect_local_store(store)
    payload = (json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    descriptor = os.open(store, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        written = os.write(descriptor, payload)
        if written != len(payload):
            print("event append was incomplete; run doctor before continuing", file=sys.stderr)
            return 2
    finally:
        os.close(descriptor)
    try:
        store.chmod(0o600)
    except OSError:
        pass
    print("recorded local privacy-safe event")
    return 0


def grouped(events: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for event in events:
        result[event["task_id"]].append(event)
    return result


def aggregate(events: list[dict[str, Any]]) -> dict[str, Any]:
    tasks = grouped(events)
    started = {task_id: task_events for task_id, task_events in tasks.items() if any(event["event"] == "task_started" for event in task_events)}
    outcomes = collections.Counter()
    inferred = 0
    corrections = 0
    validation_tasks = 0
    first_pass_verified = 0
    reworked = 0
    reopened = 0
    drift_recurring = 0
    false_completion = 0
    false_positive_gate = 0
    questions = 0
    causes = collections.Counter()
    for task_events in started.values():
        outcome, is_inferred = infer_outcome(task_events)
        names = {event["event"] for event in task_events}
        max_attempt = max((event["attempt_count"] for event in task_events), default=0)
        outcomes[outcome] += 1
        inferred += int(is_inferred)
        corrections += int("user_correction" in names)
        validation_tasks += int(any(name.startswith("validation_") for name in names))
        reopened += int("work_reopened" in names)
        drift_recurring += int("drift_recurred" in names)
        false_completion += int("unverified_claim" in names)
        false_positive_gate += int("gate_false_positive" in names)
        questions += sum(event["event"] == "question_asked" for event in task_events)
        reworked += int(max_attempt > 1 or bool(names & {"user_correction", "user_override", "work_reopened", "drift_recurred"}))
        first_pass_verified += int(
            outcome == "worked"
            and max_attempt <= 1
            and not names & {"validation_failed", "user_correction", "user_override", "work_reopened", "drift_recurred", "unverified_claim"}
        )
        causes.update(event["cause"] for event in task_events if event["event"] in NEGATIVE_EVENTS)
    total = len(started)
    priority_causes = [
        {"cause": cause, "count": count}
        for cause, count in sorted(causes.items(), key=lambda item: (-item[1], item[0]))
        if count >= 2
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "task_denominator": total,
        "outcomes": dict(sorted(outcomes.items())),
        "inference_coverage": round(inferred / total, 4) if total else None,
        "validation_coverage": round(validation_tasks / total, 4) if total else None,
        "first_pass_verified_rate": round(first_pass_verified / total, 4) if total else None,
        "correction_rate": round(corrections / total, 4) if total else None,
        "rework_rate": round(reworked / total, 4) if total else None,
        "reopen_rate": round(reopened / total, 4) if total else None,
        "drift_recurrence_rate": round(drift_recurring / total, 4) if total else None,
        "false_completion_rate": round(false_completion / total, 4) if total else None,
        "gate_false_positive_rate": round(false_positive_gate / total, 4) if total else None,
        "questions_per_task": round(questions / total, 4) if total else None,
        "negative_cause_counts": dict(sorted(causes.items())),
        "priority_causes": priority_causes,
        "metric_note": "Task-level evidence only; activity volume is not a quality metric.",
    }


def command_doctor(args: argparse.Namespace) -> int:
    store = default_store(args.store)
    events, errors = read_events(store)
    for task_id, task_events in grouped(events).items():
        starts = sum(event["event"] == "task_started" for event in task_events)
        if starts != 1:
            errors.append(f"task {task_id}: expected exactly one task_started event")
    if errors:
        print(f"doctor: {len(errors)} issue(s); no event contents printed")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"doctor: healthy local JSONL store ({len(events)} event(s), no raw-content fields)")
    return 0


def command_summarize(args: argparse.Namespace) -> int:
    events, errors = read_events(default_store(args.store))
    if errors:
        print("cannot summarize invalid event store; run doctor", file=sys.stderr)
        return 2
    print(json.dumps(aggregate(events), indent=2, sort_keys=True))
    return 0


def command_export(args: argparse.Namespace) -> int:
    if args.for_central_aggregation and not args.central_aggregation_opt_in:
        print("future central aggregation requires --central-aggregation-opt-in", file=sys.stderr)
        return 2
    events, errors = read_events(default_store(args.store))
    if errors:
        print("cannot export invalid event store; run doctor", file=sys.stderr)
        return 2
    payload = aggregate(events)
    payload["export_scope"] = "aggregate_only_no_raw_events"
    payload["central_aggregation_opt_in"] = bool(args.for_central_aggregation)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("wrote privacy-safe local aggregate; no data transmitted")
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Local privacy-preserving feedback evidence utility")
    commands = root.add_subparsers(dest="command", required=True)

    record = commands.add_parser("record", help="append one allowlisted local event")
    record.add_argument("--store", help="local JSONL path")
    record.add_argument("--task-id", required=True, type=parse_uuid)
    record.add_argument("--event", required=True, choices=sorted(EVENTS))
    record.add_argument("--cause", required=True, choices=sorted(CAUSES))
    record.add_argument("--validation-scope", default="none", choices=sorted(VALIDATION_SCOPES))
    record.add_argument("--attempt-count", default=0, type=int)
    record.add_argument("--source", default="inferred", choices=["inferred", "system"])
    record.add_argument("--verdict", choices=sorted(VERDICTS))
    record.add_argument("--inference-insufficient", action="store_true")
    record.set_defaults(func=command_record)

    doctor = commands.add_parser("doctor", help="validate a local JSONL store without printing event data")
    doctor.add_argument("--store", help="local JSONL path")
    doctor.set_defaults(func=command_doctor)

    summarize = commands.add_parser("summarize", help="print privacy-safe task-level metrics")
    summarize.add_argument("--store", help="local JSONL path")
    summarize.set_defaults(func=command_summarize)

    export = commands.add_parser("export", help="write aggregate-only JSON; never transmit")
    export.add_argument("--store", help="local JSONL path")
    export.add_argument("--output", required=True, help="local aggregate JSON path")
    export.add_argument("--for-central-aggregation", action="store_true")
    export.add_argument("--central-aggregation-opt-in", action="store_true")
    export.set_defaults(func=command_export)
    return root


def main() -> int:
    args = parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
