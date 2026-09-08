#!/usr/bin/env python3
"""Selective Intelligence production control path.

This is the authoritative bridge from minimal intent to governed execution. It
keeps reasoning/provider choice separate from project state: any available
reasoning surface may produce a validated plan or worker packet, while SI owns
intent, constraints, queues, permission checks, file application, verification,
repair state, and evidence.

The production path does not require a global model key. Deterministic discovery
and verification run through probe-backed adapters. A structured worker packet
can arrive through copy/paste, an authenticated agent CLI bridge, a local model,
or an optional managed provider without changing the session contract.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import tempfile
from functools import wraps
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import capabilities as CAP  # noqa: E402
import checkpoint as CP  # noqa: E402
import context_budget as CB  # noqa: E402
import feedback as FB  # noqa: E402
import intent_contract as IC  # noqa: E402
import lane_session as LS  # noqa: E402
import progress_checkpoint as PC  # noqa: E402
from policy_guard import PolicyDenied, PolicyGuard, guarded_run, guarded_write_text  # noqa: E402


class EngineError(RuntimeError):
    pass


def _serialized_session(function):
    """Serialize short SI state/effect transactions; never hold across a process.

    This is cooperative local ordering, not hostile-writer or crash protection.
    """
    @wraps(function)
    def run(*args, **kwargs):
        try:
            with LS.session_lock(kwargs["session_id"]):
                return function(*args, **kwargs)
        except LS.SessionConflictError as exc:
            raise EngineError(str(exc)) from exc
    return run


@_serialized_session
def make_worker_packet(*, session_id: str, task_id: str, transport: str = "packet") -> dict[str, Any]:
    if transport not in {"packet", "build"}:
        raise EngineError("unsupported worker handoff transport")
    session = LS.load_session(session_id)
    if not session:
        raise EngineError("session not found")
    try:
        CP.assert_binding(session, session["queue"].get(task_id) or {})
    except CP.CheckpointError as exc:
        raise EngineError(str(exc)) from exc
    task = session["queue"].get(task_id)
    if not task:
        raise EngineError("task not found")
    if task["status"] not in {"ready", "repairing", "failed"}:
        raise EngineError(f"task is not available for worker handoff: {task['status']}")
    # Session-owned evidence is the progress source. Rewording a request,
    # exporting a packet or re-approving the same checkpoint cannot reset it.
    current_binding = {"authorized_checkpoint_id": session.get("authorizedCheckpointId"),
                       "authorized_intent_hash": session.get("authorizedIntentHash")}
    progress = {
        "artifacts": [item.get("artifactId") for item in session.get("artifacts", [])
                      if item.get("taskId") == task_id and not item.get("tainted")
                      and not item.get("rolledBack")
                      and all(item.get(k) == v for k, v in current_binding.items())],
        "verification": [item.get("verificationId") for item in session.get("verificationAttempts", [])
                         if item.get("taskId") == task_id
                         and all(item.get(k) == v for k, v in current_binding.items())],
    }
    usage_binding = {"task_id": task_id,
                     "checkpoint_id": session["authorizedCheckpointId"],
                     "intent_hash": session["authorizedIntentHash"],
                     "progress_id": _plan_hash(progress)}
    try:
        usage = PC.admit_worker_handoff(session.get("workerHandoffUsage"), **usage_binding)
    except PC.ProgressCheckpointError as exc:
        raise EngineError(str(exc)) from exc
    workspace = Path(session["workspace"]).resolve()
    verified_adapters = [
        {
            "adapterId": adapter["adapterId"],
            "verifiedCapabilities": adapter["verifiedCapabilities"],
            "probeEvidence": adapter["probeEvidence"],
        }
        for adapter in session.get("capabilityInventory", [])
        if adapter.get("executable")
    ]
    # Export the same task material that the approval binds. A short title
    # cannot substitute for nested requirements, operations or invalidators.
    task_material = CP._task_material(task)
    task_bytes = len(json.dumps(task_material, sort_keys=True, ensure_ascii=False,
                               allow_nan=False).encode("utf-8"))
    if task_bytes > 65_536:
        raise EngineError("task instructions exceed the bounded handoff; reconcile a smaller complete task")
    # Persist admission before retrieval, including attempts that fail coverage
    # or serialization. A new process cannot restart an exhausted window.
    session["workerHandoffUsage"] = usage
    LS.save_session(session)
    try:
        context_bundle = CB.select_context(
            workspace,
            objective=session["objective"],
            task=task_material,
            acceptance_refs=task.get("acceptanceRefs", []),
        )
    except ValueError as exc:
        raise EngineError(str(exc)) from exc
    coverage = context_bundle.get("outcomeCoverage", {})
    if coverage.get("complete") is not True:
        raise EngineError(
            "context budget cannot preserve the bounded outcome; unresolved references or local dependencies remain"
        )
    packet = {
        "schemaVersion": "si.worker_packet.v3",
        "packetId": f"packet-{uuid.uuid4().hex}",
        "createdAt": _now(),
        "sessionId": session_id,
        "taskId": task_id,
        "authorized_checkpoint_id": session.get("authorizedCheckpointId"),
        "authorized_intent_hash": session.get("authorizedIntentHash"),
        "objective": session["objective"],
        "activeIntent": session["activeIntent"],
        "confirmedFacts": session.get("knownFacts", []),
        "verifiedAdapters": verified_adapters,
        "task": {
            **task_material,
            "status": task["status"],
            "attempts": copy.deepcopy(task.get("attempts", [])),
        },
        "permissions": {
            "writableRoots": session.get("writableRoots", []),
            "canonicalRoots": session.get("canonicalRoots", []),
            "prohibitedActions": [
                "canonical repository writes",
                "Git mutation including commit and push",
                "dependency installation",
                "deploy or publish",
            ],
        },
        "contextBundle": context_bundle,
        "requiredOutput": {
            "type": "object",
            "required": [
                "producer", "files", "sessionId", "taskId",
                "authorized_checkpoint_id", "authorized_intent_hash",
            ],
            "binding": {
                "sessionId": session_id,
                "taskId": task_id,
                "authorized_checkpoint_id": session.get("authorizedCheckpointId"),
                "authorized_intent_hash": session.get("authorizedIntentHash"),
            },
            "producerRequired": ["adapterId", "surface", "generatedAt"],
            "files": "object mapping safe relative paths to UTF-8 text content",
            "notes": (
                "Return the binding fields unchanged at the top level. "
                "Do not relabel results from another task or an older checkpoint. "
                "Do not include commands, secrets, absolute paths, or changes outside the bounded task."
            ),
        },
    }
    event_payload = {
        "packetId": packet["packetId"], "taskId": task_id,
        "selectedContextFiles": len(packet["contextBundle"]["selected"]),
        "authorized_checkpoint_id": packet["authorized_checkpoint_id"],
        "authorized_intent_hash": packet["authorized_intent_hash"],
    }
    event = LS.record_event(
        session, "worker.packet_exported", event_payload,
    )
    packet["eventId"] = event["eventId"]
    try:
        # Match the packet CLI's JSON formatting, including its final newline.
        # Instructions, facts, attempts and the final event ID all count.
        delivery = _build_handoff_response(session, task, packet) if transport == "build" else packet
        payload_bytes = len((json.dumps(delivery, indent=2, allow_nan=False) + "\n").encode("utf-8"))
        PC.validate_worker_handoff_size(file_count=len(context_bundle["selected"]), byte_count=payload_bytes)
    except (PC.ProgressCheckpointError, ValueError) as exc:
        raise EngineError(str(exc)) from exc
    event_payload["payloadBytes"] = payload_bytes
    usage["totalExports"] += 1
    usage["totalPayloadBytes"] += payload_bytes
    usage["tasks"][task_id].update(lastPayloadBytes=payload_bytes, lastFileCount=len(context_bundle["selected"]))
    LS.save_session(session)
    return packet


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _feedback_store(session: dict[str, Any]) -> Path | None:
    workspace = session.get("workspace")
    return Path(workspace).resolve() / FB.DEFAULT_STORE if workspace else None


def _record_feedback(
    session: dict[str, Any],
    event: str,
    *,
    cause: str = "unknown",
    validation_scope: str = "none",
    attempt_count: int = 0,
) -> bool:
    task_id = session.get("feedbackTaskId")
    store = _feedback_store(session)
    if not isinstance(task_id, str) or store is None:
        return False
    try:
        FB.record_event(
            store=store,
            task_id=task_id,
            event=event,
            cause=cause,
            validation_scope=validation_scope,
            attempt_count=attempt_count,
            source="system",
        )
    except FB.FeedbackError as exc:
        LS.record_event(session, "feedback.record_failed", {"event": event, "errorType": type(exc).__name__})
        return False
    LS.record_event(session, "feedback.recorded", {"event": event})
    return True


def _start_feedback(session: dict[str, Any]) -> None:
    if session.get("feedbackTaskId"):
        return
    session["feedbackTaskId"] = str(uuid.uuid4())
    _record_feedback(session, "task_started", cause="intent")


def _load_json(path: str | os.PathLike[str]) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise EngineError(f"JSON document must be an object: {path}")
    return value


def _safe_relative(path: str) -> Path:
    candidate = Path(path)
    if candidate.is_absolute() or not path or ".." in candidate.parts:
        raise EngineError(f"unsafe relative path: {path!r}")
    return candidate


def _guard(session: dict[str, Any]) -> PolicyGuard:
    return PolicyGuard(
        canonical_roots=session.get("canonicalRoots", []),
        writable_roots=session.get("writableRoots", []),
        prohibit_git_mutation=True,
        prohibit_dependency_install=True,
        prohibit_deploy=True,
    )


def _task_by_key(session: dict[str, Any], key: str) -> dict[str, Any] | None:
    for task in session["queue"].values():
        if task.get("metadata", {}).get("planKey") == key:
            return task
    return None


def _plan_hash(value: dict[str, Any]) -> str:
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise EngineError("plan must contain finite, JSON-compatible values") from exc
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def validate_plan(plan: dict[str, Any]) -> None:
    """Preflight the entire plan before creating any queue entries."""
    if not isinstance(plan, dict):
        raise EngineError("plan must be an object")
    _plan_hash(plan)
    tasks = plan.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise EngineError("plan.tasks must be a non-empty list")
    seen: set[str] = set()
    reserved = {
        "planKey", "kind", "authorized_checkpoint_id", "authorized_intent_hash",
        "planSpecHash", "planSource",
    }
    for index, task in enumerate(tasks):
        if not isinstance(task, dict):
            raise EngineError(f"plan task {index} must be an object")
        key = task.get("key")
        title = task.get("title")
        if not isinstance(key, str) or not key.strip() or key != key.strip():
            raise EngineError(f"plan task {index} missing or malformed key")
        if key in seen:
            raise EngineError(f"duplicate plan task key: {key}")
        if not isinstance(title, str) or not title.strip():
            raise EngineError(f"plan task {key} missing title")
        for field in ("dependencies", "tags", "invalidationConditions", "acceptanceRefs"):
            if field in task and (
                not isinstance(task[field], list)
                or not all(isinstance(v, str) and v.strip() for v in task[field])
            ):
                raise EngineError(f"plan task {key}.{field} must be a list of nonempty strings")
        unresolved = [dep for dep in task.get("dependencies", []) if dep not in seen]
        if unresolved:
            raise EngineError(f"plan is not dependency ordered; {key} precedes {', '.join(unresolved)}")
        seen.add(key)
        if not isinstance(task.get("queue", "ready"), str) or not task.get("queue", "ready").strip():
            raise EngineError(f"plan task {key}.queue must be a nonempty string")
        if not isinstance(task.get("kind", "worker"), str) or task.get("kind", "worker") not in {
            "worker", "discovery", "repair",
        }:
            raise EngineError(f"plan task {key} has an unsupported worker kind")
        metadata = task.get("metadata", {})
        if not isinstance(metadata, dict):
            raise EngineError(f"plan task {key}.metadata must be an object")
        if reserved.intersection(metadata):
            raise EngineError(f"plan task {key}.metadata cannot override routing or authorization")
        if task.get("operation") is not None and not isinstance(task["operation"], dict):
            raise EngineError(f"plan task {key}.operation must be an object or null")


def _plan_checkpoint(session: dict[str, Any]) -> dict[str, Any]:
    checkpoint = CP.current_checkpoint(session)
    if not checkpoint or checkpoint.get("status") not in {"proposed", "correction_mode", "approved"}:
        raise EngineError("plan requires a current proposed or approved checkpoint")
    try:
        CP._assert_current_intent(session, checkpoint)
    except CP.CheckpointError as exc:
        raise EngineError(str(exc)) from exc
    return checkpoint


def _plan_source(session: dict[str, Any]) -> dict[str, str]:
    checkpoint = _plan_checkpoint(session)
    return {
        "sessionId": session["sessionId"],
        "checkpointId": checkpoint["checkpoint_id"],
        "intentHash": checkpoint["intent_hash"],
    }


def _plan_text(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _plan_text(child)
    elif isinstance(value, list):
        for child in value:
            yield from _plan_text(child)


def _validate_plan_source_and_intent(session: dict[str, Any], plan: dict[str, Any]) -> None:
    validate_plan(plan)
    source = plan.get("source")
    expected = _plan_source(session)
    if not isinstance(source, dict) or set(source) != set(expected):
        raise EngineError("plan source is required; regenerate from the current plan packet")
    for field, value in expected.items():
        if not isinstance(source.get(field), str) or source[field] != value:
            raise EngineError(f"plan source {field} does not match the current checkpoint")
    intent = session["activeIntent"]
    rejected = IC._product_model_targets(list(intent.get("superseded_concepts") or []))
    if rejected:
        for task in plan["tasks"]:
            # Identifiers are not product assertions. Inspect the actual task
            # instructions, including nested metadata, with the existing bounded
            # product-model classifier. This is not universal semantic proof.
            instructions = {key: value for key, value in task.items() if key != "key"}
            if any(IC._conflicts_with_product_model(text) for text in _plan_text(instructions)):
                raise EngineError("plan conflicts with the rejected product model; regenerate the affected plan")


def _stage_pending_plan(
    session: dict[str, Any], plan: dict[str, Any], *, initial_request: bool = False,
) -> None:
    """Bind a proposal before approval; never relabel an imported old plan.

    Only a plan supplied with the initial request may omit its source. Later
    imports must echo the plan packet they were generated from. Source fields
    correlate a proposal with intent; they are not producer attestation.
    """
    validate_plan(plan)
    pending = copy.deepcopy(plan)
    checkpoint = _plan_checkpoint(session)
    if checkpoint["status"] not in {"proposed", "correction_mode"}:
        raise EngineError("a changed plan needs a proposed checkpoint, not an existing approval")
    if initial_request and "source" not in pending:
        pending["source"] = _plan_source(session)
    _validate_plan_source_and_intent(session, pending)
    digest = _plan_hash(pending)
    previous = checkpoint.get("pending_plan_hash")
    if previous is not None and previous != digest:
        raise EngineError("checkpoint already has a different plan; reconcile before approval")
    checkpoint["pending_plan_hash"] = digest
    checkpoint["planned_next_actions"] = [task["title"] for task in pending["tasks"]]
    session["pendingPlan"] = pending


def _assert_plan_snapshot(session: dict[str, Any], plan: dict[str, Any]) -> None:
    _validate_plan_source_and_intent(session, plan)
    checkpoint = _plan_checkpoint(session)
    if not checkpoint.get("pending_plan_hash") or checkpoint["pending_plan_hash"] != _plan_hash(plan):
        raise EngineError("plan differs from the checkpoint proposal; reconcile before execution")
    if checkpoint.get("planned_next_actions") != [task["title"] for task in plan["tasks"]]:
        raise EngineError("checkpoint actions differ from the plan proposal")


def make_plan_packet(*, session_id: str) -> dict[str, Any]:
    """Read-only proposed-intent handoff; grants no execution authority."""
    session = LS.load_session(session_id)
    if not session:
        raise EngineError("session not found")
    return {
        "schemaVersion": "si.plan_packet.v1",
        "source": _plan_source(session),
        "activeIntent": copy.deepcopy(session["activeIntent"]),
        "requiredOutput": {
            "required": ["source", "tasks"],
            "source": _plan_source(session),
            "notes": (
                "Return source unchanged from this packet. Generate tasks for this intent; "
                "do not relabel an old plan. List dependencies before dependents. "
                "A proposed plan grants no execution permission."
            ),
        },
    }


@_serialized_session
def stage_plan(*, session_id: str, plan: dict[str, Any]) -> dict[str, Any]:
    """Persist a fresh proposal for review without granting execution authority."""
    session = LS.load_session(session_id)
    if not session:
        raise EngineError("session not found")
    _stage_pending_plan(session, plan)
    LS.record_event(session, "plan.proposed", {"planHash": _plan_hash(plan)})
    LS.save_session(session)
    return {
        "sessionId": session_id,
        "currentCheckpoint": CP.checkpoint_public_view(CP.current_checkpoint(session)),
        "pendingPlan": copy.deepcopy(session["pendingPlan"]),
        "executionLocked": session.get("executionLocked"),
        "generationAuthority": session.get("generationAuthority"),
    }


def add_plan_tasks(session: dict[str, Any], plan: dict[str, Any]) -> dict[str, str]:
    try:
        CP.require_authorized_checkpoint(session)
    except CP.CheckpointError as exc:
        raise EngineError(str(exc)) from exc
    plan = copy.deepcopy(plan)
    _assert_plan_snapshot(session, plan)
    # Queue construction is an in-memory transaction. A failed insertion must
    # not leave half a plan in the caller's session. Disk/concurrent transactions
    # remain the persistence owner's responsibility.
    staged = copy.deepcopy(session)
    existing: dict[str, dict[str, Any]] = {}
    for task in staged["queue"].values():
        key = task.get("metadata", {}).get("planKey")
        if not key or task.get("status") in {"cancelled", "invalidated"} or task.get("tainted"):
            continue
        if key in existing:
            raise EngineError(f"ambiguous existing plan task: {key}")
        existing[key] = task
    key_to_id: dict[str, str] = {}
    added: list[str] = []
    for spec in plan["tasks"]:
        metadata = {
            **copy.deepcopy(spec.get("metadata", {})),
            "planKey": spec["key"], "kind": spec.get("kind", "worker"),
            "planSpecHash": _plan_hash(spec), "planSource": copy.deepcopy(plan["source"]),
        }
        expected = {
            "title": spec["title"], "queue": spec.get("queue", "ready"),
            "dependencies": [key_to_id[dep] for dep in spec.get("dependencies", [])],
            "tags": spec.get("tags", []), "acceptanceRefs": spec.get("acceptanceRefs", []),
            "invalidationConditions": spec.get("invalidationConditions", []),
            "operation": spec.get("operation"),
        }
        if spec["key"] in existing:
            task = existing[spec["key"]]
            try:
                CP.assert_binding(staged, task)
            except CP.CheckpointError as exc:
                raise EngineError(str(exc)) from exc
            if any(task.get(key) != value for key, value in expected.items()):
                raise EngineError(f"existing task differs from current plan: {spec['key']}")
            if any(task.get("metadata", {}).get(key) != value for key, value in metadata.items()):
                raise EngineError(f"existing task provenance differs from current plan: {spec['key']}")
        else:
            task = LS.add_task(
                staged, title=expected["title"], queue=expected["queue"],
                dependencies=expected["dependencies"], tags=expected["tags"],
                acceptance_refs=expected["acceptanceRefs"],
                invalidation_conditions=expected["invalidationConditions"],
                operation=expected["operation"], metadata=metadata,
            )
            added.append(spec["key"])
        key_to_id[spec["key"]] = task["taskId"]
    LS.record_event(staged, "plan.tasks_added", {
        "planId": plan.get("planId"), "taskKeys": added,
        "authorized_checkpoint_id": staged.get("authorizedCheckpointId"),
        "authorized_intent_hash": staged.get("authorizedIntentHash"),
    })
    CP.receipt(staged, action="plan.tasks_add", details={"planId": plan.get("planId"), "taskKeys": added})
    session.clear()
    session.update(staged)
    return key_to_id


def run_discovery_tasks(session: dict[str, Any]) -> None:
    try:
        CP.require_authorized_checkpoint(session)
    except CP.CheckpointError as exc:
        raise EngineError(str(exc)) from exc
    workspace = Path(session["workspace"]).resolve()
    for task in list(LS.ready_tasks(session)):
        if task.get("metadata", {}).get("kind") != "discovery":
            continue
        ok, reason = LS.transition_task(session, task["taskId"], "running")
        if not ok:
            raise EngineError(reason)
        # Capability probe is read-only evidence collection in the disposable workspace.
        reports = CAP.inventory(probe_root=workspace)
        session["capabilityInventory"] = reports
        LS.add_fact(
            session,
            "available SI execution capabilities were probed in the disposable workspace",
            {
                "verifiedAdapterIds": [r["adapterId"] for r in reports if r["executable"]],
                "reportCount": len(reports),
            },
        )
        task["attempts"].append(
            {
                "attemptId": f"attempt-{len(task['attempts']) + 1}",
                "type": "capability_discovery",
                "timestamp": _now(),
                "verifiedAdapterIds": [r["adapterId"] for r in reports if r["executable"]],
                "authorized_checkpoint_id": session.get("authorizedCheckpointId"),
                "authorized_intent_hash": session.get("authorizedIntentHash"),
            }
        )
        ok, reason = LS.transition_task(session, task["taskId"], "verifying")
        if not ok:
            raise EngineError(reason)
        # Discovery verification is the successful probe evidence itself; no
        # separate mutation or generated artifact is accepted as proof.
        ok, reason = LS.transition_task(session, task["taskId"], "complete")
        if not ok:
            raise EngineError(reason)


def _apply_pending_plan(session: dict[str, Any], plan: dict[str, Any] | None = None) -> None:
    pending = plan if plan is not None else session.get("pendingPlan")
    if pending is None:
        if _plan_checkpoint(session).get("pending_plan_hash"):
            raise EngineError("checkpoint plan is missing; reconcile before approval")
        return
    add_plan_tasks(session, pending)
    run_discovery_tasks(session)
    session.pop("pendingPlan", None)


def start_project(
    *,
    request: str,
    workspace: str,
    canonical_roots: list[str],
    plan: dict[str, Any] | None = None,
    structured_intent: dict[str, Any] | None = None,
    auto_approve: bool = False,
) -> dict[str, Any]:
    """SI interprets → emit proposed checkpoint → approve → then plan/execute.

    Model interpretation is a proposal, not authority. Passing ``plan`` stores it
    as pending until the checkpoint is approved (or ``auto_approve`` for tests).
    """
    workspace_path = Path(workspace).resolve()
    # Validate paths before any filesystem write. Defer mkdir until approval.
    for root in canonical_roots:
        canonical = Path(root).resolve()
        try:
            workspace_path.relative_to(canonical)
        except ValueError:
            pass
        else:
            raise EngineError("disposable workspace must not be inside a canonical repository")
    session = LS.new_session(
        request,
        workspace=str(workspace_path),
        canonical_roots=[str(Path(root).resolve()) for root in canonical_roots],
        writable_roots=[str(workspace_path)],
        structured_intent=structured_intent,
    )
    if plan is not None:
        _stage_pending_plan(session, plan, initial_request=True)
    if auto_approve:
        checkpoint = CP.current_checkpoint(session)
        if not checkpoint:
            raise EngineError("missing initial checkpoint")
        CP.approve_checkpoint(session, checkpoint["checkpoint_id"])
        workspace_path.mkdir(parents=True, exist_ok=True)
        _start_feedback(session)
        _apply_pending_plan(session)
    LS.save_session(session)
    return session


@_serialized_session
def approve_project(
    *,
    session_id: str,
    checkpoint_id: str | None = None,
    intent_hash: str | None = None,
    plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    session = LS.load_session(session_id)
    if not session:
        raise EngineError("session not found")
    checkpoint_id = checkpoint_id or session.get("currentCheckpointId")
    if not checkpoint_id:
        raise EngineError("no checkpoint to approve")
    # Validate the complete proposal before granting authority, creating a
    # workspace, recording feedback, or dispatching discovery.
    if plan is not None:
        _stage_pending_plan(session, plan)
    if "pendingPlan" in session:
        _assert_plan_snapshot(session, session["pendingPlan"])
    elif _plan_checkpoint(session).get("pending_plan_hash"):
        raise EngineError("checkpoint plan is missing; reconcile before approval")
    try:
        CP.approve_checkpoint(
            session,
            checkpoint_id,
            expected_intent_hash=intent_hash,
        )
    except CP.CheckpointError as exc:
        raise EngineError(str(exc)) from exc
    workspace = session.get("workspace")
    if workspace:
        Path(workspace).resolve().mkdir(parents=True, exist_ok=True)
    _start_feedback(session)
    _apply_pending_plan(session)
    LS.save_session(session)
    return session


def apply_text_gate(
    *,
    session_id: str,
    raw_response: str,
    checkpoint_id: str | None = None,
    intent_hash: str | None = None,
) -> dict[str, Any]:
    """Apply a non-Platynum text-gate reply (APPROVE / CORRECT: …).

    Same transactions as Platynum Approve / Correct buttons.
    """
    import text_gate as TG

    parsed = TG.parse_text_gate(raw_response)
    if parsed["action"] == "approve":
        session = approve_project(
            session_id=session_id,
            checkpoint_id=checkpoint_id,
            intent_hash=intent_hash,
        )
        return {
            "action": "approve",
            "session": session,
            "siCheckpointId": session.get("authorizedCheckpointId") or session.get("currentCheckpointId"),
            "intentHash": session.get("authorizedIntentHash"),
            "executionLocked": session.get("executionLocked"),
        }
    session, result = interrupt_project(
        session_id=session_id,
        correction=parsed["correction"],
        disliked_checkpoint_id=checkpoint_id,
    )
    new_cp = result.get("newCheckpoint") or {}
    return {
        "action": "correct",
        "session": session,
        "operation": result.get("operation"),
        "interruptedCheckpointId": result.get("interruptedCheckpointId"),
        "newCheckpoint": new_cp,
        "siCheckpointId": new_cp.get("checkpoint_id"),
        "intentHash": new_cp.get("intent_hash") or result.get("newIntentHash"),
        "executionLocked": True,
        "resumeRequiresApproval": True,
    }

@_serialized_session
def interrupt_project(
    *,
    session_id: str,
    correction: str,
    structured_intent: dict[str, Any] | None = None,
    disliked_checkpoint_id: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Atomic SI session-state interrupt endpoint for Platynum 👎 wiring.

    Updates SI session state: generationAuthority false, cancel queued tasks,
    request-cancel running/verifying/repairing, freeze mutations, taint
    rejected-checkpoint effects, capture correction, emit a new proposed
    checkpoint. Resume requires approve of the new checkpoint.

    Claim scope: session-state interruption only until a product connection
    proves model generation, tool dispatch, and external workers actually stop.
    Platynum live-steering UI (merged PR #2) remains observational until it
    calls this transaction.
    """
    session = LS.load_session(session_id)
    if not session:
        raise EngineError("session not found")
    try:
        result = CP.interrupt(
            session,
            correction=correction,
            structured_intent=structured_intent,
            disliked_checkpoint_id=disliked_checkpoint_id,
        )
    except CP.CheckpointError as exc:
        raise EngineError(str(exc)) from exc
    _record_feedback(session, "user_correction", cause="intent")
    LS.save_session(session)
    return session, result


@_serialized_session
def correct_project(
    *,
    session_id: str,
    correction: str,
    replacement_plan: dict[str, Any] | None = None,
    structured_intent: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Compile a correction into a canonical interrupt state transition.

    SI owns the interpretation. A caller-supplied ``replacement_plan`` is stored
    as pending only; it is not authority and cannot execute until the new
    checkpoint is approved. A replacement generated before this interrupt has
    stale provenance: obtain the new plan packet and import a fresh plan through
    approve_project instead of relabelling the old proposal.
    """
    session, result = interrupt_project(
        session_id=session_id,
        correction=correction,
        structured_intent=structured_intent,
    )
    # Normalize interrupt result to the correction contract surface.
    result = {
        **result,
        "invalidatedTaskIds": list(result.get("cancelledTaskIds") or []),
        "preservedCompletedTaskIds": [],
    }
    if replacement_plan is not None:
        # The correction has already been saved by interrupt_project. Rejecting
        # a stale/unbound replacement must never undo that correction.
        _stage_pending_plan(session, replacement_plan)
        LS.record_event(
            session,
            "plan.pending_after_correction",
            {"planId": replacement_plan.get("planId"), "note": "not authoritative until checkpoint approve"},
        )
        LS.save_session(session)
    return session, result

def validate_worker_artifact(artifact: dict[str, Any]) -> None:
    if not isinstance(artifact, dict):
        raise EngineError("worker artifact must be an object")
    for field in ("sessionId", "taskId", "authorized_checkpoint_id", "authorized_intent_hash"):
        if not isinstance(artifact.get(field), str) or not artifact[field].strip():
            raise EngineError(f"worker artifact {field} is required; regenerate from the current packet")
    files = artifact.get("files")
    producer = artifact.get("producer")
    if not isinstance(files, dict) or not files:
        raise EngineError("worker artifact files must be a non-empty object")
    if not all(isinstance(name, str) and isinstance(content, str) for name, content in files.items()):
        raise EngineError("worker artifact files must map relative paths to text")
    if not isinstance(producer, dict):
        raise EngineError("worker artifact requires producer provenance")
    for field in ("adapterId", "surface", "generatedAt"):
        if not isinstance(producer.get(field), str) or not producer[field].strip():
            raise EngineError(f"worker artifact producer.{field} is required")


def _replace_bytes(target: Path, content: bytes, mode: int | None = None) -> None:
    """Replace one file atomically; multi-file rollback is handled by the caller."""
    descriptor, name = tempfile.mkstemp(prefix=".si-restore-", dir=target.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            temporary.chmod(mode)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


@_serialized_session
def apply_worker_artifact(
    *, session_id: str, task_id: str, artifact: dict[str, Any],
) -> dict[str, Any]:
    validate_worker_artifact(artifact)
    session = LS.load_session(session_id)
    if not session:
        raise EngineError("session not found")
    task = session["queue"].get(task_id)
    if not task:
        raise EngineError("task not found")
    if artifact["sessionId"] != session_id or artifact["taskId"] != task_id:
        raise EngineError("worker artifact belongs to another session or task")
    try:
        CP.assert_binding(session, task)
        CP.assert_binding(session, artifact)
    except CP.CheckpointError as exc:
        raise EngineError(str(exc)) from exc
    if task["status"] not in {"ready", "repairing"}:
        raise EngineError(f"task is not executable: {task['status']}")
    guard = _guard(session)
    workspace = Path(session["workspace"]).resolve()
    prepared: list[dict[str, Any]] = []
    targets: set[Path] = set()
    for relative_name, content in artifact["files"].items():
        relative = _safe_relative(relative_name)
        target = (workspace / relative).resolve()
        decision = guard.authorize(session_id=session_id, task_id=task_id,
                                   action={"kind": "filesystem.write", "path": str(target)})
        if not decision["allowed"]:
            raise PolicyDenied(decision)
        if target in targets:
            raise EngineError("multiple file names resolve to the same target")
        if target.exists() and not target.is_file():
            raise EngineError("file target is an existing directory or special file")
        if any(parent.exists() and not parent.is_dir() for parent in target.parents):
            raise EngineError("file target has a non-directory parent")
        targets.add(target)
        prepared.append({"relative": relative, "target": target, "content": content,
                         "before": target.read_bytes() if target.exists() else None,
                         "mode": target.stat().st_mode & 0o777 if target.exists() else None})
    if any(parent in targets for target in targets for parent in target.parents):
        raise EngineError("file targets conflict with another file's parent directory")

    # Stage the complete batch before replacing any original. Keep preimages
    # until the session save succeeds; recover caught failures without claiming
    # crash-atomicity, isolation across different sessions, or external writers.
    stages: list[Path] = []
    committed: list[dict[str, Any]] = []
    created_dirs: list[Path] = []
    written: list[dict[str, Any]] = []
    original_revision = session.get("persistenceRevision", 0)
    try:
        ok, reason = LS.transition_task(session, task_id, "running")
        if not ok:
            raise EngineError(reason)
        for item in prepared:
            target = item["target"]
            missing = []
            parent = target.parent
            while not parent.exists():
                missing.append(parent)
                parent = parent.parent
            for parent in reversed(missing):
                parent.mkdir()
                created_dirs.append(parent)
            descriptor, name = tempfile.mkstemp(prefix=".si-stage-", dir=target.parent)
            os.close(descriptor)
            stage = Path(name)
            stages.append(stage)
            decision, evidence = guarded_write_text(stage, item["content"], guard=guard,
                                                   session_id=session_id, task_id=task_id)
            if stage.is_symlink() or stage.read_bytes() != item["content"].encode("utf-8"):
                raise EngineError("staged bytes differ from the supplied file content")
            if item["mode"] is not None:
                stage.chmod(item["mode"])
            item.update(stage=stage, evidence=evidence, decision=decision)
        current = LS.load_session(session_id)
        if not current or current.get("persistenceRevision", 0) != original_revision:
            raise EngineError("session changed during file staging; no new authority inherited")
        CP.assert_binding(current, artifact)
        for item in prepared:
            target = item["target"]
            actual = target.read_bytes() if target.exists() else None
            if (target.is_symlink() or actual != item["before"]
                    or (item["mode"] is not None and target.stat().st_mode & 0o777 != item["mode"])):
                raise EngineError("file changed during staging; refusing to overwrite other work")
            decision = guard.authorize(session_id=session_id, task_id=task_id,
                                       action={"kind": "filesystem.write", "path": str(target)})
            if not decision["allowed"]:
                raise PolicyDenied(decision)
            os.replace(item["stage"], target)
            committed.append(item)
            evidence = item["evidence"]
            LS.record_policy_decision(session, decision)
            record = {"artifactId": evidence["evidenceId"], "taskId": task_id,
                      "artifactType": "file", "relativePath": item["relative"].as_posix(),
                      "absolutePath": str(target), "sha256": evidence["sha256"],
                      "bytes": evidence["bytes"], "producer": artifact["producer"],
                      "createdAt": evidence["timestamp"],
                      "authorized_checkpoint_id": session.get("authorizedCheckpointId"),
                      "authorized_intent_hash": session.get("authorizedIntentHash")}
            LS.record_artifact(session, record)
            written.append(record)
        task["attempts"].append({
            "attemptId": f"attempt-{len(task['attempts']) + 1}",
            "type": "structured_worker_artifact", "producer": artifact["producer"],
            "fileArtifactIds": [record["artifactId"] for record in written], "timestamp": _now(),
            "authorized_checkpoint_id": session.get("authorizedCheckpointId"),
            "authorized_intent_hash": session.get("authorizedIntentHash"),
        })
        ok, reason = LS.transition_task(session, task_id, "verifying")
        if not ok:
            raise EngineError(reason)
        CP.receipt(session, action="filesystem.write", details={"taskId": task_id, "files": [w["relativePath"] for w in written]})
        LS.save_session(session)
        return {"session": session, "written": written}
    except Exception as exc:
        unresolved = []
        for item in reversed(committed):
            target = item["target"]
            try:
                # Never roll back an unrecognized later write by someone else.
                if target.is_symlink() or target.read_bytes() != item["content"].encode("utf-8"):
                    raise OSError("target changed after SI wrote it")
                if item["before"] is None:
                    target.unlink()
                else:
                    _replace_bytes(target, item["before"], item["mode"])
            except OSError:
                unresolved.append(item["relative"].as_posix())
        try:
            current = LS.load_session(session_id)
            if current:
                current_task = current.get("queue", {}).get(task_id)
                if current_task and current.get("authorizedCheckpointId") == artifact["authorized_checkpoint_id"]:
                    current_task["status"] = "failed"
                for record in current.get("artifacts", []):
                    if record.get("artifactId") in {w["artifactId"] for w in written}:
                        record.update(tainted=True, rolledBack=record.get("relativePath") not in unresolved)
                LS.record_event(current, "filesystem.batch_failed", {
                    "taskId": task_id, "errorType": type(exc).__name__,
                    "rollbackComplete": not unresolved, "unresolvedPaths": unresolved,
                    "authorized_checkpoint_id": artifact["authorized_checkpoint_id"],
                })
                LS.save_session(current)
        except (OSError, ValueError, LS.SessionConflictError):
            unresolved.append("session recovery record could not be saved")
        if unresolved:
            raise EngineError("file application failed; recovery incomplete: " + "; ".join(unresolved)) from exc
        if isinstance(exc, (PolicyDenied, EngineError)):
            raise
        raise EngineError("file application failed; earlier changes were restored: " + str(exc)) from exc
    finally:
        for stage in stages:
            stage.unlink(missing_ok=True)
        for parent in reversed(created_dirs):
            try:
                parent.rmdir()
            except OSError:
                pass


def _normalize_command(command: dict[str, Any], workspace: Path) -> tuple[list[str], Path]:
    argv = command.get("argv")
    if not isinstance(argv, list) or not argv or not all(isinstance(v, str) for v in argv):
        raise EngineError("verification command argv must be a non-empty list of strings")
    cwd_value = command.get("cwd", ".")
    if not isinstance(cwd_value, str):
        raise EngineError("verification command cwd must be a string")
    cwd_rel = _safe_relative(cwd_value) if cwd_value not in {"", "."} else Path(".")
    cwd = (workspace / cwd_rel).resolve()
    try:
        cwd.relative_to(workspace)
    except ValueError as exc:
        raise EngineError("verification cwd escaped disposable workspace") from exc
    return list(argv), cwd


def verify_task(
    *, session_id: str, task_id: str, command: dict[str, Any],
) -> dict[str, Any]:
    # Reserve one attempt under the session lock, then release it so a person's
    # correction can cancel SI's verification process while it is running.
    with LS.session_lock(session_id):
        session = LS.load_session(session_id)
        if not session:
            raise EngineError("session not found")
        task = session["queue"].get(task_id)
        if not task:
            raise EngineError("task not found")
        try:
            CP.assert_binding(session, task)
        except CP.CheckpointError as exc:
            raise EngineError(str(exc)) from exc
        if task["status"] != "verifying":
            raise EngineError(f"task is not awaiting verification: {task['status']}")
        if task.get("activeVerification"):
            raise EngineError("verification is already running; reconcile an abandoned attempt before retrying")
        workspace = Path(session["workspace"]).resolve()
        argv, cwd = _normalize_command(command, workspace)
        guard = _guard(session)
        binding = {"sessionId": session_id, "taskId": task_id,
                   "authorized_checkpoint_id": session["authorizedCheckpointId"],
                   "authorized_intent_hash": session["authorizedIntentHash"]}
        attempt_id = f"verification-run-{uuid.uuid4().hex}"
        task["activeVerification"] = {**binding, "attemptId": attempt_id, "startedAt": _now()}
        LS.save_session(session)

    def current_attempt(current):
        if not current:
            return False
        current_task = current.get("queue", {}).get(task_id) or {}
        if (current_task.get("activeVerification") or {}).get("attemptId") != attempt_id:
            return False
        try:
            CP.assert_binding(current, binding)
        except CP.CheckpointError:
            return False
        return current_task.get("status") == "verifying"

    def interrupted() -> bool:
        try:
            return not current_attempt(LS.load_session(session_id))
        except (OSError, ValueError):
            return True

    try:
        decision, evidence = guarded_run(argv, cwd=cwd, guard=guard, session_id=session_id,
                                        task_id=task_id, cancel_check=interrupted)
    except Exception as exc:
        with LS.session_lock(session_id):
            current = LS.load_session(session_id)
            if current:
                current_task = current.get("queue", {}).get(task_id) or {}
                owns_attempt = (current_task.get("activeVerification") or {}).get("attemptId") == attempt_id
                valid = current_attempt(current)
                if owns_attempt:
                    current_task.pop("activeVerification", None)
                if valid:
                    LS.transition_task(current, task_id, "failed", reason="verification process did not return evidence")
                if isinstance(exc, PolicyDenied):
                    LS.record_policy_decision(current, exc.decision)
                LS.record_event(current, "verification.process_failed", {
                    **binding, "attemptId": attempt_id, "errorType": type(exc).__name__,
                })
                LS.save_session(current)
        if isinstance(exc, PolicyDenied):
            raise
        raise EngineError("verification process failed: " + str(exc)) from exc

    with LS.session_lock(session_id):
        session = LS.load_session(session_id)
        if not session:
            raise EngineError("session disappeared during verification")
        task = session.get("queue", {}).get(task_id)
        if not task:
            raise EngineError("task disappeared during verification")
        valid = current_attempt(session)
        if (task.get("activeVerification") or {}).get("attemptId") == attempt_id:
            task.pop("activeVerification", None)
        LS.record_policy_decision(session, decision)
        evidence = {**evidence, **binding, "verificationRunId": attempt_id}
        LS.record_command(session, evidence)
        if evidence.get("cancelled") or not valid:
            evidence["invalidated"] = True
            _record_feedback(session, "evidence_invalidated", cause="intent", validation_scope="focused")
            LS.save_session(session)
            return {"session": session, "passed": False, "cancelled": True,
                    "verification": None, "commandEvidence": evidence, "repairTask": None}
        passed = evidence["exitCode"] == 0
        verification = LS.record_verification(session, task_id, evidence["evidenceId"], passed)
        repair_task = None
        if passed:
            ok, reason = LS.transition_task(session, task_id, "complete")
            if not ok:
                raise EngineError(reason)
            _record_feedback(session, "validation_passed", cause="unknown", validation_scope="focused")
        else:
            ok, reason = LS.transition_task(session, task_id, "repairing", reason="verification command failed")
            if not ok:
                raise EngineError(reason)
            repair_task = LS.add_task(session, title=f"Repair: {task['title']}", queue="repair",
                dependencies=[], tags=list(task.get("tags", [])) + ["repair"],
                acceptance_refs=list(task.get("acceptanceRefs", [])),
                invalidation_conditions=list(task.get("invalidationConditions", [])),
                metadata={"kind": "repair", "originalTaskId": task_id,
                          "originalTask": CP._task_material(task),
                          "verificationCommand": command, "failureEvidenceId": evidence["evidenceId"]})
            _record_feedback(session, "validation_failed", cause="unknown", validation_scope="focused")
        CP.receipt(session, action="process.run", details={"taskId": task_id, "passed": passed})
        LS.save_session(session)
        return {"session": session, "passed": passed, "cancelled": False,
                "verification": verification, "commandEvidence": evidence, "repairTask": repair_task}


def verify_repair(
    *, session_id: str, repair_task_id: str, command: dict[str, Any],
) -> dict[str, Any]:
    result = verify_task(session_id=session_id, task_id=repair_task_id, command=command)
    if not result["passed"]:
        return result
    with LS.session_lock(session_id):
        session = LS.load_session(session_id)
        if not session:
            raise EngineError("session disappeared after repair verification")
        repair_task = session["queue"][repair_task_id]
        try:
            CP.assert_binding(session, result["commandEvidence"])
        except CP.CheckpointError as exc:
            raise EngineError("repair authority changed before completion: " + str(exc)) from exc
        original_id = repair_task.get("metadata", {}).get("originalTaskId")
        if original_id and session["queue"].get(original_id, {}).get("status") == "repairing":
            ok, reason = LS.transition_task(session, original_id, "complete", reason=f"repair task {repair_task_id} passed verification")
            if not ok:
                raise EngineError(reason)
        session["completionEvidence"].append({
            "completionId": f"complete-{len(session['completionEvidence']) + 1}", "timestamp": _now(),
            "originalTaskId": original_id, "repairTaskId": repair_task_id,
            "verificationId": result["verification"]["verificationId"],
            "commandEvidenceId": result["commandEvidence"]["evidenceId"],
            "authorized_checkpoint_id": session["authorizedCheckpointId"],
            "authorized_intent_hash": session["authorizedIntentHash"],
        })
        LS.save_session(session)
        result["session"] = session
        return result


@_serialized_session
def authorize_only(*, session_id: str, task_id: str, action: dict[str, Any]) -> dict[str, Any]:
    session = LS.load_session(session_id)
    if not session:
        raise EngineError("session not found")
    if task_id not in session["queue"]:
        raise EngineError("task not found")
    try:
        CP.require_authorized_checkpoint(session)
        CP.assert_binding(session, session["queue"][task_id])
    except CP.CheckpointError as exc:
        raise EngineError(str(exc)) from exc
    decision = _guard(session).authorize(session_id=session_id, task_id=task_id, action=action)
    decision = dict(decision)
    decision["authorized_checkpoint_id"] = session.get("authorizedCheckpointId")
    decision["authorized_intent_hash"] = session.get("authorizedIntentHash")
    LS.record_policy_decision(session, decision)
    LS.save_session(session)
    return decision


def _first_ready_worker(session: dict[str, Any]) -> dict[str, Any] | None:
    for task in LS.ready_tasks(session):
        if task.get("metadata", {}).get("kind") in {"worker", "repair"}:
            return task
    return None


def default_plan() -> dict[str, Any]:
    return {
        "planId": "compatibility-intake-v1",
        "tasks": [
            {
                "key": "discovery",
                "title": "Inspect project and probe available capabilities",
                "queue": "discovery",
                "kind": "discovery",
                "tags": ["discovery", "capabilities"],
            },
            {
                "key": "worker_packet",
                "title": "Produce a bounded implementation artifact for the accepted intent",
                "queue": "ready",
                "kind": "worker",
                "dependencies": ["discovery"],
                "tags": ["implementation"],
                "invalidationConditions": ["implementation contract changes", "acceptance criterion changes"],
            },
        ],
    }


def cmd_start(args: argparse.Namespace) -> int:
    try:
        plan = _load_json(args.plan) if args.plan else default_plan()
        structured = _load_json(args.intent_override) if args.intent_override else None
        session = start_project(
            request=args.request,
            workspace=args.workspace,
            canonical_roots=args.canonical_root or [],
            plan=plan,
            structured_intent=structured,
            auto_approve=bool(args.auto_approve),
        )
    except (EngineError, LS.SessionConflictError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc), "code": "start_failed"}))
        return 2
    print(json.dumps(LS.summary(session), indent=2))
    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    try:
        plan = _load_json(args.plan) if args.plan else None
        session = approve_project(
            session_id=args.session,
            checkpoint_id=args.checkpoint,
            intent_hash=getattr(args, "intent_hash", None),
            plan=plan,
        )
    except (EngineError, LS.SessionConflictError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc), "code": "approve_failed"}))
        return 2
    print(json.dumps(LS.summary(session), indent=2))
    return 0


def cmd_text_gate(args: argparse.Namespace) -> int:
    try:
        result = apply_text_gate(
            session_id=args.session,
            raw_response=args.response,
            checkpoint_id=args.checkpoint,
            intent_hash=args.intent_hash,
        )
    except (EngineError, LS.SessionConflictError, ValueError, OSError) as exc:
        code = "text_gate_failed"
        if "invalid text gate" in str(exc).lower() or "execution locked" in str(exc).lower():
            code = "bad_input"
        print(json.dumps({"error": str(exc), "code": code}))
        return 2
    session = result.pop("session")
    payload = {
        "sessionId": session["sessionId"],
        **{k: v for k, v in result.items() if k != "newCheckpoint"},
        "state": LS.global_state(session),
        "executionLocked": session.get("executionLocked"),
        "mutationFrozen": session.get("mutationFrozen"),
        "currentCheckpoint": CP.checkpoint_public_view(CP.current_checkpoint(session))
        if CP.current_checkpoint(session)
        else None,
    }
    if result.get("newCheckpoint"):
        payload["newCheckpoint"] = CP.checkpoint_public_view(result["newCheckpoint"])
    print(json.dumps(payload, indent=2))
    return 0


def _cmd_correction(args: argparse.Namespace, *, interrupt_only: bool = False) -> int:
    # Optional model/file inputs must not suppress the person's plain correction.
    # Invalid attachments are reported separately from the persisted correction.
    attachment_errors: dict[str, str] = {}
    structured = None
    if args.intent_override:
        try:
            structured = _load_json(args.intent_override)
            IC.validate_override(structured)
        except (EngineError, LS.SessionConflictError, ValueError, OSError) as exc:
            structured = None
            attachment_errors["intent_override"] = str(exc)
    try:
        if interrupt_only:
            session, result = interrupt_project(
                session_id=args.session, correction=args.correction,
                structured_intent=structured, disliked_checkpoint_id=args.checkpoint,
            )
        else:
            session, result = correct_project(
                session_id=args.session, correction=args.correction,
                structured_intent=structured,
            )
    except (EngineError, LS.SessionConflictError, ValueError, OSError) as exc:
        print(json.dumps({"error": str(exc), "code": "correction_failed", "correctionSaved": False}))
        return 2

    # Read replacement files only after interrupt_project has saved the correction.
    # Old plans are never stamped with the fresh checkpoint to make them pass.
    if not interrupt_only and args.plan:
        try:
            replacement = _load_json(args.plan)
            _stage_pending_plan(session, replacement)
            LS.record_event(session, "plan.pending_after_correction", {
                "planId": replacement.get("planId"), "note": "not authoritative until checkpoint approve",
            })
            LS.save_session(session)
        except (EngineError, LS.SessionConflictError, ValueError, OSError) as exc:
            attachment_errors["replacement_plan"] = str(exc)
    payload = {
        "sessionId": session["sessionId"],
        **{key: value for key, value in result.items() if key != "newCheckpoint"},
        "newCheckpoint": CP.checkpoint_public_view(result["newCheckpoint"]),
        "state": LS.global_state(session),
        "executionLocked": session.get("executionLocked"),
        "mutationFrozen": session.get("mutationFrozen"),
        "pendingPlan": bool(session.get("pendingPlan")),
        "queue": list(session["queue"].values()),
        "correctionSaved": True,
        "planPacket": make_plan_packet(session_id=session["sessionId"]),
        "nextAction": "generate_fresh_plan_then_stage_for_approval",
    }
    if attachment_errors:
        payload.update(code="correction_saved_attachment_rejected", attachmentErrors=attachment_errors)
    print(json.dumps(payload, indent=2))
    return 2 if attachment_errors else 0


def cmd_interrupt(args: argparse.Namespace) -> int:
    return _cmd_correction(args, interrupt_only=True)


def cmd_correct(args: argparse.Namespace) -> int:
    return _cmd_correction(args)


def cmd_apply(args: argparse.Namespace) -> int:
    try:
        artifact = _load_json(args.artifact)
        # The compatibility build route supplies no task override. Route using
        # the returned result itself; never infer or manufacture its bindings.
        task_id = args.task if args.task is not None else artifact.get("taskId")
        result = apply_worker_artifact(session_id=args.session, task_id=task_id, artifact=artifact)
    except PolicyDenied as exc:
        print(json.dumps({"error": str(exc), "decision": exc.decision, "code": "policy_denied"}, indent=2))
        return 3
    except (EngineError, LS.SessionConflictError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc), "code": "apply_failed"}))
        return 2
    print(json.dumps({"sessionId": args.session, "written": result["written"], "state": LS.global_state(result["session"])}, indent=2))
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    try:
        command = _load_json(args.command)
        result = verify_task(session_id=args.session, task_id=args.task, command=command)
    except PolicyDenied as exc:
        print(json.dumps({"error": str(exc), "decision": exc.decision, "code": "policy_denied"}, indent=2))
        return 3
    except (EngineError, LS.SessionConflictError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc), "code": "verify_failed"}))
        return 2
    print(json.dumps({"sessionId": args.session, "passed": result["passed"], "commandEvidence": result["commandEvidence"], "repairTask": result["repairTask"], "state": LS.global_state(result["session"])}, indent=2))
    return 0 if result["passed"] else 5


def cmd_verify_repair(args: argparse.Namespace) -> int:
    try:
        command = _load_json(args.command)
        result = verify_repair(session_id=args.session, repair_task_id=args.task, command=command)
    except PolicyDenied as exc:
        print(json.dumps({"error": str(exc), "decision": exc.decision, "code": "policy_denied"}, indent=2))
        return 3
    except (EngineError, LS.SessionConflictError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc), "code": "repair_verify_failed"}))
        return 2
    print(json.dumps({"sessionId": args.session, "passed": result["passed"], "commandEvidence": result["commandEvidence"], "state": LS.global_state(result["session"])}, indent=2))
    return 0 if result["passed"] else 5


def cmd_authorize(args: argparse.Namespace) -> int:
    try:
        action = _load_json(args.action)
        decision = authorize_only(session_id=args.session, task_id=args.task, action=action)
    except (EngineError, LS.SessionConflictError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc), "code": "authorization_failed"}))
        return 2
    print(json.dumps(decision, indent=2))
    return 0 if decision["allowed"] else 3


def cmd_plan_packet(args: argparse.Namespace) -> int:
    try:
        packet = make_plan_packet(session_id=args.session)
    except (EngineError, LS.SessionConflictError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc), "code": "plan_packet_failed"}))
        return 2
    print(json.dumps(packet, indent=2))
    return 0


def cmd_stage_plan(args: argparse.Namespace) -> int:
    try:
        result = stage_plan(session_id=args.session, plan=_load_json(args.plan))
    except (EngineError, LS.SessionConflictError, ValueError, OSError) as exc:
        print(json.dumps({"error": str(exc), "code": "stage_plan_failed"}))
        return 2
    print(json.dumps(result, indent=2))
    return 0


def cmd_packet(args: argparse.Namespace) -> int:
    try:
        packet = make_worker_packet(session_id=args.session, task_id=args.task)
        if args.output:
            output = Path(args.output).expanduser().resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(packet, indent=2), encoding="utf-8")
    except (EngineError, LS.SessionConflictError, ValueError, OSError) as exc:
        print(json.dumps({"error": str(exc), "code": "packet_failed"}))
        return 2
    print(json.dumps(packet, indent=2))
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    session = LS.load_session(args.session)
    if not session:
        print(json.dumps({"error": "session not found"}))
        return 4
    print(json.dumps(LS.summary(session), indent=2))
    return 0


# Compatibility transport uses the same authority and result validation owners.
# Planning alone is not approval. External callers must follow the emitted
# checkpoint and submit a fresh source-bound plan/result, not relabel old work.
def cmd_plan(args: argparse.Namespace) -> int:
    return cmd_start(argparse.Namespace(
        request=args.idea, workspace=args.workspace, canonical_root=args.canonical_root,
        plan=args.plan, intent_override=None, auto_approve=False,
    ))


def _build_handoff_response(session: dict[str, Any], task: dict[str, Any], packet: dict[str, Any]) -> dict[str, Any]:
    return {
        "sessionId": session["sessionId"], "code": "worker_input_required",
        "task": task, "workerPacket": packet, "humanActions": [],
        "state": LS.global_state(session),
        "note": "Generate from this packet; return its unchanged bindings with the actual result.",
    }


def cmd_build(args: argparse.Namespace) -> int:
    if args.artifact:
        return cmd_apply(argparse.Namespace(session=args.session, task=None, artifact=args.artifact))
    try:
        session = LS.load_session(args.session)
        if not session:
            print(json.dumps({"error": "invalid or expired session", "code": "invalid_session"}))
            return 4
        task = _first_ready_worker(session)
        if not task:
            print(json.dumps({"error": "no ready worker task", "code": "no_ready_task"}))
            return 4
        packet = make_worker_packet(session_id=session["sessionId"], task_id=task["taskId"], transport="build")
    except (EngineError, LS.SessionConflictError, ValueError, OSError) as exc:
        print(json.dumps({"error": str(exc), "code": "build_handoff_failed"}))
        return 2
    print(json.dumps(_build_handoff_response(session, task, packet), indent=2))
    return 3


def main() -> int:
    parser = argparse.ArgumentParser(description="SI intent-locked production control path")
    sub = parser.add_subparsers(dest="command", required=True)

    start = sub.add_parser("start")
    start.add_argument("--request", required=True)
    start.add_argument("--workspace", required=True)
    start.add_argument("--canonical-root", action="append", default=[])
    start.add_argument("--plan")
    start.add_argument("--intent-override")
    start.add_argument(
        "--auto-approve",
        action="store_true",
        help="Approve the emitted checkpoint immediately (tests/compat only; production should approve explicitly)",
    )
    start.set_defaults(func=cmd_start)

    approve = sub.add_parser("approve")
    approve.add_argument("--session", required=True)
    approve.add_argument("--checkpoint")
    approve.add_argument(
        "--intent-hash",
        dest="intent_hash",
        help="Fail closed unless this matches the checkpoint intent_hash",
    )
    approve.add_argument("--plan")
    approve.set_defaults(func=cmd_approve)

    text_gate_cmd = sub.add_parser(
        "text-gate",
        help="Apply APPROVE or CORRECT: <instruction> (non-Platynum clients)",
    )
    text_gate_cmd.add_argument("--session", required=True)
    text_gate_cmd.add_argument("--response", required=True, help="Raw APPROVE or CORRECT: … text")
    text_gate_cmd.add_argument("--checkpoint")
    text_gate_cmd.add_argument("--intent-hash", dest="intent_hash")
    text_gate_cmd.set_defaults(func=cmd_text_gate)

    interrupt_cmd = sub.add_parser("interrupt")
    interrupt_cmd.add_argument("--session", required=True)
    interrupt_cmd.add_argument("--correction", required=True)
    interrupt_cmd.add_argument("--checkpoint")
    interrupt_cmd.add_argument("--intent-override")
    interrupt_cmd.set_defaults(func=cmd_interrupt)

    correct = sub.add_parser("correct")
    correct.add_argument("--session", required=True)
    correct.add_argument("--correction", required=True)
    correct.add_argument("--plan", help="Legacy input: cannot delay correction; use its fresh plan packet then stage-plan")
    correct.add_argument("--intent-override")
    correct.set_defaults(func=cmd_correct)

    apply_cmd = sub.add_parser("apply")
    apply_cmd.add_argument("--session", required=True)
    apply_cmd.add_argument("--task", required=True)
    apply_cmd.add_argument("--artifact", required=True)
    apply_cmd.set_defaults(func=cmd_apply)

    verify = sub.add_parser("verify")
    verify.add_argument("--session", required=True)
    verify.add_argument("--task", required=True)
    verify.add_argument("--command", required=True)
    verify.set_defaults(func=cmd_verify)

    repair = sub.add_parser("verify-repair")
    repair.add_argument("--session", required=True)
    repair.add_argument("--task", required=True)
    repair.add_argument("--command", required=True)
    repair.set_defaults(func=cmd_verify_repair)

    authorize = sub.add_parser("authorize")
    authorize.add_argument("--session", required=True)
    authorize.add_argument("--task", required=True)
    authorize.add_argument("--action", required=True)
    authorize.set_defaults(func=cmd_authorize)

    plan_packet = sub.add_parser("plan-packet")
    plan_packet.add_argument("--session", required=True)
    plan_packet.set_defaults(func=cmd_plan_packet)

    stage = sub.add_parser("stage-plan", help="Store a fresh source-bound proposal without approving or executing it")
    stage.add_argument("--session", required=True)
    stage.add_argument("--plan", required=True)
    stage.set_defaults(func=cmd_stage_plan)

    packet = sub.add_parser("packet")
    packet.add_argument("--session", required=True)
    packet.add_argument("--task", required=True)
    packet.add_argument("--output")
    packet.set_defaults(func=cmd_packet)

    show = sub.add_parser("show")
    show.add_argument("--session", required=True)
    show.set_defaults(func=cmd_show)

    plan = sub.add_parser("plan")
    plan.add_argument("--idea", required=True)
    plan.add_argument("--workspace", required=True)
    plan.add_argument("--canonical-root", action="append", default=[])
    plan.add_argument("--plan")
    plan.set_defaults(func=cmd_plan)

    build = sub.add_parser("build")
    build.add_argument("--session", required=True)
    build.add_argument("--artifact")
    build.set_defaults(func=cmd_build)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
