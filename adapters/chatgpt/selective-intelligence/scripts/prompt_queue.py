#!/usr/bin/env python3
"""Prompt queue cache for burst prompting.

This utility stores user requests in a local JSONL queue so build intent does not
drift across branch churn, context resets, or fast turn-taking.

Life-cycle:
queued -> in_progress -> fleshed/discarded

Each item remains in the queue until it is explicitly finished and pruned.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
import uuid
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
DEFAULT_QUEUE = Path(".selective-intelligence/prompt-queue.jsonl")
DEFAULT_SNAPSHOT = Path(".selective-intelligence/prompt-queue-snapshot.json")

STATUS_CHOICES = {"queued", "in_progress", "fleshed", "discarded"}
OPEN_STATUS = {"queued", "in_progress"}
ARCHIVE_STATUSES = {"fleshed", "discarded"}
TRANSITIONS = {
    "queued": {"queued", "in_progress", "discarded"},
    "in_progress": {"in_progress", "fleshed", "discarded"},
    "fleshed": {"fleshed", "discarded"},
    "discarded": {"discarded", "fleshed"},
}

PROMPT_REDACTION_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9._~+/-]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    re.compile(r"\bgho_[A-Za-z0-9_]{20,}\b"),
)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def has_symlink_component(path: Path) -> bool:
    absolute = path.absolute()
    cursor = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        cursor = cursor / part
        if cursor.is_symlink():
            return True
    return False


def mask_prompt(value: str) -> str:
    masked = value
    for pattern in PROMPT_REDACTION_PATTERNS:
        masked = pattern.sub("[redacted-by-queue]", masked)
    return masked


def parse_uuid(value: Any) -> bool:
    try:
        parsed = uuid.UUID(str(value))
    except (TypeError, ValueError):
        return False
    return parsed.version == 4 and parsed.variant == uuid.RFC_4122


def parse_prompt_input(args: argparse.Namespace) -> str:
    if args.prompt is not None:
        return args.prompt.strip()
    if args.prompt_file is not None:
        with Path(args.prompt_file).open("r", encoding="utf-8") as handle:
            return handle.read().strip()
    if args.prompt_stdin:
        value = sys.stdin.read().strip()
        if value:
            return value
    raise ValueError("prompt must come from --prompt, --prompt-file, or stdin")


def queue_path(args: argparse.Namespace) -> Path:
    return Path(args.queue).expanduser() if args.queue else DEFAULT_QUEUE


def snapshot_path(args: argparse.Namespace) -> Path:
    return Path(args.snapshot).expanduser() if args.snapshot else DEFAULT_SNAPSHOT


def read_queue(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    if has_symlink_component(path):
        return [], ["queue path may not include symlink components"]
    if not path.exists():
        return [], []
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    with path.open("r", encoding="utf-8") as handle:
        for index, raw in enumerate(handle, 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                record = json.loads(raw)
            except json.JSONDecodeError:
                errors.append(f"line {index}: not valid JSON")
                continue
            issue = validate_record(record)
            if issue:
                errors.append(f"line {index}: {issue}")
                continue
            records.append(record)
    return records, errors


def write_queue(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    try:
        temporary.replace(path)
    except PermissionError:
        temporary.unlink(missing_ok=True)
        if path.exists():
            path.unlink()
        with path.open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")


def validate_record(record: Any) -> str | None:
    if not isinstance(record, dict):
        return "record must be an object"
    required = {"schema_version", "queue_id", "status", "created_at", "updated_at", "prompt_hash", "prompt_excerpt", "source"}
    missing = sorted(required - set(record))
    if missing:
        return f"missing required keys: {', '.join(missing)}"
    extras = set(record) - {
        "schema_version",
        "queue_id",
        "status",
        "created_at",
        "updated_at",
        "prompt_hash",
        "prompt_excerpt",
        "source",
        "branch",
        "pre_pr_ref",
        "owner_id",
        "run_id",
        "labels",
        "meta",
        "started_at",
        "fleshed_at",
    }
    if extras:
        return f"unknown keys: {', '.join(sorted(extras))}"
    if record["schema_version"] != SCHEMA_VERSION:
        return f"schema_version must be {SCHEMA_VERSION}"
    if record["status"] not in STATUS_CHOICES:
        return f"invalid status: {record['status']}"
    if not parse_uuid(record["queue_id"]):
        return "queue_id must be a UUIDv4"
    for field in ("created_at", "updated_at"):
        try:
            parsed = dt.datetime.fromisoformat(str(record[field]).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return f"{field} must be ISO-8601 with timezone"
        if parsed.tzinfo is None:
            return f"{field} must include timezone"
    if not isinstance(record["prompt_hash"], str) or len(record["prompt_hash"]) != 64:
        return "prompt_hash must be a sha256 hex digest"
    if not isinstance(record["prompt_excerpt"], str) or not record["prompt_excerpt"].strip():
        return "prompt_excerpt must be non-empty"
    if not isinstance(record["source"], str) or not record["source"].strip():
        return "source must be non-empty"
    if record.get("labels") is not None and (not isinstance(record["labels"], list) or any(not isinstance(item, str) for item in record["labels"])):
        return "labels must be a list of strings"
    if record.get("meta") is not None and not isinstance(record["meta"], dict):
        return "meta must be an object when provided"
    return None


def validate_snapshot(snapshot: Any) -> str | None:
    if not isinstance(snapshot, dict):
        return "snapshot must be an object"
    required = {
        "schema_version",
        "snapshot_id",
        "queue_id",
        "expected_status",
        "created_at",
    }
    missing = sorted(required - set(snapshot))
    if missing:
        return f"missing required keys: {', '.join(missing)}"
    extras = set(snapshot) - {
        "schema_version",
        "snapshot_id",
        "queue_id",
        "owner_id",
        "branch",
        "expected_status",
        "expected_position",
        "step",
        "created_at",
        "pre_pr_ref",
        "source",
    }
    if extras:
        return f"unknown keys: {', '.join(sorted(extras))}"
    if snapshot["schema_version"] != SCHEMA_VERSION:
        return f"schema_version must be {SCHEMA_VERSION}"
    if not parse_uuid(snapshot["snapshot_id"]):
        return "snapshot_id must be a UUIDv4"
    if not parse_uuid(snapshot["queue_id"]):
        return "queue_id must be a UUIDv4"
    if snapshot["expected_status"] not in STATUS_CHOICES:
        return "expected_status must be a valid queue status"
    if snapshot.get("expected_position") is not None:
        if not isinstance(snapshot["expected_position"], int) or snapshot["expected_position"] < 1:
            return "expected_position must be a positive integer"
    try:
        parsed = dt.datetime.fromisoformat(str(snapshot["created_at"]).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return "created_at must be ISO-8601 with timezone"
    if parsed.tzinfo is None:
        return "created_at must include timezone"
    if snapshot.get("step") is not None and not isinstance(snapshot["step"], str):
        return "step must be a string when provided"
    return None


def build_record(prompt: str, source: str, branch: str | None, pre_pr_ref: str | None, owner_id: str | None, run_id: str | None, labels: list[str] | None, meta: str | None) -> dict[str, Any]:
    now = utc_now()
    prompt_redacted = mask_prompt(prompt)
    prompt_hash = hashlib.sha256(prompt_redacted.encode("utf-8")).hexdigest()
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "queue_id": str(uuid.uuid4()),
        "status": "queued",
        "created_at": now,
        "updated_at": now,
        "prompt_hash": prompt_hash,
        "prompt_excerpt": prompt_redacted[:180],
        "source": source,
    }
    if branch:
        payload["branch"] = branch
    if pre_pr_ref:
        payload["pre_pr_ref"] = pre_pr_ref
    if owner_id:
        payload["owner_id"] = owner_id
    if run_id:
        payload["run_id"] = run_id
    if labels:
        payload["labels"] = labels
    if meta:
        try:
            payload["meta"] = json.loads(meta)
        except json.JSONDecodeError as exc:
            raise ValueError(f"--meta must be JSON: {exc}") from exc
    return payload


def add_record(path: Path, record: dict[str, Any]) -> None:
    records, errors = read_queue(path)
    if errors:
        print("queue is invalid; run doctor first", file=sys.stderr)
        for issue in errors:
            print(f"- {issue}", file=sys.stderr)
        raise SystemExit(2)
    records.append(record)
    write_queue(path, records)


def find_record(records: list[dict[str, Any]], queue_id: str) -> tuple[int, dict[str, Any]]:
    for index, record in enumerate(records):
        if record["queue_id"] == queue_id:
            return index, record
    raise KeyError(queue_id)


def patch_record(
    records: list[dict[str, Any]],
    queue_id: str,
    status: str,
    *,
    owner_id: str | None = None,
    force: bool = False,
) -> None:
    index, record = find_record(records, queue_id)
    current_status = record["status"]
    if status != current_status and not force and status not in TRANSITIONS[current_status]:
        raise ValueError(
            f"invalid status transition {current_status} -> {status} "
            f"(allowed: {', '.join(sorted(TRANSITIONS[current_status]))})"
        )
    now = utc_now()
    record["status"] = status
    record["updated_at"] = now
    if owner_id:
        record["owner_id"] = owner_id
    if status == "in_progress":
        record["started_at"] = now
    elif status in ARCHIVE_STATUSES:
        record["fleshed_at"] = now
    records[index] = record


def open_position_index(
    records: list[dict[str, Any]],
    queue_id: str,
    branch: str | None = None,
) -> int | None:
    scope = [record for record in records if record["status"] in OPEN_STATUS and (branch is None or record.get("branch") == branch)]
    scope.sort(key=lambda item: (item["created_at"], item["queue_id"]))
    for index, record in enumerate(scope, start=1):
        if record["queue_id"] == queue_id:
            return index
    return None


def command_enqueue(args: argparse.Namespace) -> int:
    path = queue_path(args)
    try:
        prompt = parse_prompt_input(args)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if not prompt:
        print("prompt cannot be empty", file=sys.stderr)
        return 2
    labels = [] if args.label is None else args.label
    try:
        record = build_record(
            prompt=prompt,
            source=args.source,
            branch=args.branch,
            pre_pr_ref=args.pre_pr_ref,
            owner_id=args.owner,
            run_id=args.run_id,
            labels=labels,
            meta=args.meta,
        )
    except ValueError as exc:
        print(f"{exc}", file=sys.stderr)
        return 2
    add_record(path, record)
    print(record["queue_id"])
    print(f"queued under {path}")
    return 0


def command_list(args: argparse.Namespace) -> int:
    path = queue_path(args)
    records, errors = read_queue(path)
    if errors:
        print("queue invalid; run doctor first", file=sys.stderr)
        for issue in errors:
            print(f"- {issue}", file=sys.stderr)
        return 2
    statuses = set(args.status)
    filtered = [record for record in records if not statuses or record["status"] in statuses]
    if args.branch:
        filtered = [record for record in filtered if record.get("branch") == args.branch]
    if args.owner:
        filtered = [record for record in filtered if record.get("owner_id") == args.owner]
    if args.json:
        print(json.dumps({"count": len(filtered), "records": filtered}, indent=2, sort_keys=True))
        return 0
    if not filtered:
        print("queue empty")
        return 0
    for record in filtered:
        print(
            f"{record['queue_id']}  [{record['status']}]  {record['created_at']}  "
            f"{record['prompt_excerpt']}  branch={record.get('branch','-')}"
        )
    return 0


def command_next(args: argparse.Namespace) -> int:
    path = queue_path(args)
    records, errors = read_queue(path)
    if errors:
        print("queue invalid; run doctor first", file=sys.stderr)
        for issue in errors:
            print(f"- {issue}", file=sys.stderr)
        return 2

    open_records = [
        record
        for record in records
        if record["status"] == "queued"
        and (not args.branch or record.get("branch") == args.branch)
        and (not args.owner or record.get("owner_id") is None or record.get("owner_id") == args.owner)
    ]
    if not open_records:
        print("no queued item available")
        return 0
    open_records.sort(key=lambda record: (record["created_at"], record["queue_id"]))
    selected = open_records[0]
    if args.json:
        print(
            json.dumps(
                {
                    "queue_id": selected["queue_id"],
                    "branch": selected.get("branch"),
                    "prompt_excerpt": selected["prompt_excerpt"],
                    "status": selected["status"],
                    "source": selected["source"],
                },
                sort_keys=True,
                indent=2,
            )
        )
        return 0
    print(
        f"{selected['queue_id']}  [{selected['status']}]  {selected['created_at']}  "
        f"{selected['prompt_excerpt']}  branch={selected.get('branch', '-')}"
    )
    return 0


def command_claim(args: argparse.Namespace) -> int:
    path = queue_path(args)
    records, errors = read_queue(path)
    if errors:
        print("queue invalid; run doctor first", file=sys.stderr)
        for issue in errors:
            print(f"- {issue}", file=sys.stderr)
        return 2
    try:
        _, target = find_record(records, args.queue_id)
        branch = args.branch or target.get("branch")
        if not args.force:
            for record in records:
                if (
                    record["status"] == "in_progress"
                    and record["queue_id"] != args.queue_id
                    and not args.no_serial
                    and (branch is None or record.get("branch") == branch)
                ):
                    print(
                        f"another item is already in_progress for this branch: {record['queue_id']}",
                        file=sys.stderr,
                    )
                    return 2
                if args.owner and record.get("owner_id") == args.owner and record["status"] == "in_progress" and record["queue_id"] != args.queue_id:
                    print(f"owner {args.owner} already owns in_progress item {record['queue_id']}", file=sys.stderr)
                    return 2
        patch_record(records, args.queue_id, "in_progress", owner_id=args.owner, force=args.force)
    except KeyError:
        print(f"unknown queue id: {args.queue_id}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    write_queue(path, records)
    print(f"claimed {args.queue_id}")
    return 0


def command_set_status(args: argparse.Namespace) -> int:
    path = queue_path(args)
    records, errors = read_queue(path)
    if errors:
        print("queue invalid; run doctor first", file=sys.stderr)
        for issue in errors:
            print(f"- {issue}", file=sys.stderr)
        return 2
    try:
        patch_record(records, args.queue_id, args.status, owner_id=args.owner, force=args.force)
    except KeyError:
        print(f"unknown queue id: {args.queue_id}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    write_queue(path, records)
    print(f"updated {args.queue_id} -> {args.status}")
    return 0


def command_remove(args: argparse.Namespace) -> int:
    path = queue_path(args)
    records, errors = read_queue(path)
    if errors:
        print("queue invalid; run doctor first", file=sys.stderr)
        for issue in errors:
            print(f"- {issue}", file=sys.stderr)
        return 2
    try:
        removed = None
        kept: list[dict[str, Any]] = []
        for record in records:
            if record["queue_id"] == args.queue_id:
                removed = record
            else:
                kept.append(record)
        if removed is None:
            raise KeyError(args.queue_id)
        write_queue(path, kept)
    except KeyError:
        print(f"unknown queue id: {args.queue_id}", file=sys.stderr)
        return 2
    print(f"removed {args.queue_id}")
    if args.dump:
        print(json.dumps(removed, indent=2, sort_keys=True))
    return 0


def command_snapshot(args: argparse.Namespace) -> int:
    path = queue_path(args)
    target_path = snapshot_path(args)
    records, errors = read_queue(path)
    if errors:
        print("queue invalid; run doctor first", file=sys.stderr)
        for issue in errors:
            print(f"- {issue}", file=sys.stderr)
        return 2
    if not args.queue_id:
        print("queue-id is required", file=sys.stderr)
        return 2
    _, target = find_record(records, args.queue_id)
    if args.expected_position is not None and args.expected_position < 1:
        print("--expected-position must be a positive integer", file=sys.stderr)
        return 2
    if args.owner and target.get("owner_id") and target["owner_id"] != args.owner:
        print("owner mismatch for snapshot target", file=sys.stderr)
        return 2
    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "snapshot_id": str(uuid.uuid4()),
        "queue_id": args.queue_id,
        "owner_id": args.owner or target.get("owner_id"),
        "branch": args.branch or target.get("branch"),
        "expected_status": args.expected_status,
        "expected_position": args.expected_position,
        "step": args.step,
        "created_at": utc_now(),
        "pre_pr_ref": target.get("pre_pr_ref"),
        "source": target.get("source"),
    }
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(json.dumps(snapshot, sort_keys=True, indent=2), encoding="utf-8")
    print(f"snapshot written to {target_path}")
    if args.json:
        print(json.dumps(snapshot, sort_keys=True, indent=2))
    return 0


def command_check(args: argparse.Namespace) -> int:
    path = queue_path(args)
    snapshot_file = snapshot_path(args)
    queue_records, queue_errors = read_queue(path)
    if queue_errors:
        print("queue invalid; run doctor first", file=sys.stderr)
        for issue in queue_errors:
            print(f"- {issue}", file=sys.stderr)
        return 2

    try:
        snapshot_raw = snapshot_file.read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"snapshot missing: {snapshot_file}", file=sys.stderr)
        return 2
    try:
        snapshot = json.loads(snapshot_raw)
    except json.JSONDecodeError:
        print("snapshot is not valid JSON", file=sys.stderr)
        return 2
    issue = validate_snapshot(snapshot)
    if issue:
        print(f"snapshot invalid: {issue}", file=sys.stderr)
        return 2

    queue_id = args.queue_id or snapshot["queue_id"]
    try:
        _, record = find_record(queue_records, queue_id)
    except KeyError:
        output = {
            "decision": "interrupt",
            "queue_id": queue_id,
            "reason": ["target queue item missing"],
        }
        print(json.dumps(output, sort_keys=True))
        return 2

    reasons: list[str] = []
    expected_status = args.expected_status or snapshot.get("expected_status")
    if expected_status and record["status"] != expected_status:
        if expected_status in OPEN_STATUS and record["status"] in ARCHIVE_STATUSES:
            print(
                json.dumps(
                    {
                        "decision": "complete",
                        "queue_id": queue_id,
                        "queue_status": record["status"],
                        "queue_branch": record.get("branch"),
                    },
                    sort_keys=True,
                )
            )
            return 0
        reasons.append(
            f"status mismatch: snapshot expects {expected_status}, queue is {record['status']}"
        )

    if args.check_owner and snapshot.get("owner_id"):
        if record.get("owner_id") != snapshot["owner_id"]:
            reasons.append(
                f"owner mismatch: snapshot expects {snapshot['owner_id']}, queue has {record.get('owner_id') or 'none'}"
            )

    if args.check_branch and snapshot.get("branch"):
        if record.get("branch") != snapshot["branch"]:
            reasons.append(
                f"branch mismatch: snapshot expects {snapshot['branch']}, queue has {record.get('branch') or 'none'}"
            )

    if args.enforce_sequential and record["status"] in OPEN_STATUS:
        branch = snapshot.get("branch")
        position = open_position_index(queue_records, queue_id, branch=branch)
        if position is None:
            reasons.append("snapshot target is not in open order for branch scope")
        else:
            expected_position = snapshot.get("expected_position", 1)
            if position != expected_position:
                reasons.append(
                    f"non-sequential step: queue item is position {position} but snapshot expects {expected_position} "
                    f"for branch={branch or 'global'}"
                )

    if reasons:
        output = {
            "decision": "interrupt",
            "queue_id": queue_id,
            "queue_status": record["status"],
            "queue_branch": record.get("branch"),
            "reason": reasons,
        }
        print(json.dumps(output, sort_keys=True))
        return 2

    output = {
        "decision": "continue",
        "queue_id": queue_id,
        "queue_status": record["status"],
        "queue_branch": record.get("branch"),
        "position": open_position_index(queue_records, queue_id, branch=record.get("branch")),
    }
    print(json.dumps(output, sort_keys=True))
    return 0


def command_doctor(args: argparse.Namespace) -> int:
    path = queue_path(args)
    records, errors = read_queue(path)
    for error in errors:
        print(f"- {error}", file=sys.stderr)
    if errors:
        print(f"prompt queue invalid: {len(errors)} issue(s)", file=sys.stderr)
        return 1
    status_counts: dict[str, int] = {status: 0 for status in sorted(STATUS_CHOICES)}
    for record in records:
        status_counts[record["status"]] = status_counts.get(record["status"], 0) + 1
    open_count = sum(record["status"] in OPEN_STATUS for record in records)
    print(f"queue file: {path}")
    print(f"total: {len(records)}")
    print(f"open: {open_count}")
    for status in sorted(status_counts):
        print(f"- {status}: {status_counts[status]}")
    if args.json:
        print(json.dumps({"count": len(records), "status_counts": status_counts}, indent=2, sort_keys=True))
    return 0


def command_prune(args: argparse.Namespace) -> int:
    path = queue_path(args)
    records, errors = read_queue(path)
    if errors:
        print("queue invalid; run doctor first", file=sys.stderr)
        for issue in errors:
            print(f"- {issue}", file=sys.stderr)
        return 2
    keep = [record for record in records if record["status"] in OPEN_STATUS]
    if len(keep) == len(records):
        print("nothing to prune")
        return 0
    write_queue(path, keep)
    print(f"pruned {len(records) - len(keep)} closed item(s)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local prompt queue for burst prompting")
    commands = parser.add_subparsers(dest="command", required=True)

    enqueue = commands.add_parser("enqueue", help="Add a new prompt to the queue")
    enqueue.add_argument("--queue", help="queue path")
    prompt_source = enqueue.add_mutually_exclusive_group(required=True)
    prompt_source.add_argument("--prompt", help="prompt text")
    prompt_source.add_argument("--prompt-file", dest="prompt_file", help="path to file containing prompt text")
    prompt_source.add_argument("--prompt-stdin", dest="prompt_stdin", action="store_true", help="read prompt text from stdin")
    enqueue.add_argument("--source", required=True, help="human channel or pipeline name")
    enqueue.add_argument("--branch", help="current branch name")
    enqueue.add_argument("--pre-pr-ref", help="pre-PR or planned PR ID/reference")
    enqueue.add_argument("--owner", help="worker/agent owner id")
    enqueue.add_argument("--run-id", help="current run or session id")
    enqueue.add_argument("--label", action="append", default=[], help="optional queue labels")
    enqueue.add_argument("--meta", help="optional JSON metadata")
    enqueue.set_defaults(func=command_enqueue)

    list_cmd = commands.add_parser("list", help="List queued prompts")
    list_cmd.add_argument("--queue")
    list_cmd.add_argument("--status", action="append", choices=sorted(STATUS_CHOICES), default=[], help="filter by status")
    list_cmd.add_argument("--branch", help="filter by branch")
    list_cmd.add_argument("--owner", help="filter by owner")
    list_cmd.add_argument("--json", action="store_true")
    list_cmd.set_defaults(func=command_list)

    next_cmd = commands.add_parser("next", help="Print next queued item by created-at order")
    next_cmd.add_argument("--queue")
    next_cmd.add_argument("--branch", help="optional branch filter")
    next_cmd.add_argument("--owner", help="optional owner filter")
    next_cmd.add_argument("--json", action="store_true")
    next_cmd.set_defaults(func=command_next)

    claim = commands.add_parser("claim", help="Mark a queued prompt as in_progress")
    claim.add_argument("--queue")
    claim.add_argument("--queue-id", required=True)
    claim.add_argument("--owner", help="worker/agent owner id")
    claim.add_argument("--branch", help="limit serialization check to this branch (defaults to target branch)")
    claim.add_argument("--no-serial", action="store_true", help="do not block when another item is in_progress")
    claim.add_argument("--force", action="store_true", help="overwrite owner/state restrictions when needed for recovery")
    claim.set_defaults(func=command_claim)

    set_status = commands.add_parser("set-status", help="Set queue item status")
    set_status.add_argument("--queue")
    set_status.add_argument("--queue-id", required=True)
    set_status.add_argument("--status", required=True, choices=sorted(STATUS_CHOICES - {"queued"}))
    set_status.add_argument("--owner", help="worker/agent owner id")
    set_status.add_argument(
        "--force", action="store_true", help="allow non-standard transition when this is explicit recovery"
    )
    set_status.set_defaults(func=command_set_status)

    snapshot_cmd = commands.add_parser("snapshot", help="Write a manager snapshot for the current in-progress slice")
    snapshot_cmd.add_argument("--queue", help="queue path")
    snapshot_cmd.add_argument("--snapshot", help="snapshot path")
    snapshot_cmd.add_argument("--queue-id", required=True)
    snapshot_cmd.add_argument("--owner", help="expected owner id")
    snapshot_cmd.add_argument("--branch", help="expected branch override")
    snapshot_cmd.add_argument("--expected-status", default="in_progress", choices=sorted(STATUS_CHOICES))
    snapshot_cmd.add_argument("--expected-position", type=int, help="expected sequential position in branch scope")
    snapshot_cmd.add_argument("--step", help="short textual step name")
    snapshot_cmd.add_argument("--json", action="store_true")
    snapshot_cmd.set_defaults(func=command_snapshot)

    check_cmd = commands.add_parser("check", help="Evaluate snapshot against queue and return continue/interrupt")
    check_cmd.add_argument("--queue", help="queue path")
    check_cmd.add_argument("--snapshot", help="snapshot path")
    check_cmd.add_argument("--queue-id", help="override queue id in the snapshot")
    check_cmd.add_argument("--expected-status", choices=sorted(STATUS_CHOICES), help="override expected status")
    check_cmd.add_argument("--check-owner", action="store_true", help="compare owner_id from snapshot and queue")
    check_cmd.add_argument("--check-branch", action="store_true", help="compare branch from snapshot and queue")
    check_cmd.add_argument("--enforce-sequential", action="store_true", help="interrupt if open item is out of branch order")
    check_cmd.set_defaults(func=command_check)

    remove_cmd = commands.add_parser("remove", help="Remove queue item after it is safely archived")
    remove_cmd.add_argument("--queue")
    remove_cmd.add_argument("--queue-id", required=True)
    remove_cmd.add_argument("--dump", action="store_true", help="print removed item JSON")
    remove_cmd.set_defaults(func=command_remove)

    doctor = commands.add_parser("doctor", help="Validate local queue file")
    doctor.add_argument("--queue")
    doctor.add_argument("--json", action="store_true")
    doctor.set_defaults(func=command_doctor)

    prune = commands.add_parser("prune", help="Remove all closed (fleshed/discarded) items")
    prune.add_argument("--queue")
    prune.set_defaults(func=command_prune)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
