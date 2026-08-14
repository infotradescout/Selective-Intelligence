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
import hashlib
import json
import os
import re
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
import lane_session as LS  # noqa: E402
from policy_guard import PolicyDenied, PolicyGuard, guarded_run, guarded_write_text  # noqa: E402


class EngineError(RuntimeError):
    pass


_CONTEXT_EXCLUDED_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".cache", "dist", "build"}
_SENSITIVE_NAME_PATTERNS = (
    re.compile(r"^\.env(?:\..+)?$", re.I),
    re.compile(r"(?:secret|credential|token|private[_-]?key)", re.I),
    re.compile(r"(?:^|[._-])id_rsa(?:$|[._-])", re.I),
    re.compile(r"\.(?:pem|p12|pfx|key)$", re.I),
)
_SENSITIVE_CONTENT = re.compile(
    r"BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY|(?:api[_-]?key|secret|token|password)\s*[:=]\s*['\"]?[^\s'\"]{8,}",
    re.I,
)


def _context_bundle(workspace: Path, *, max_files: int = 50, max_bytes: int = 65536, max_file_bytes: int = 16384) -> dict[str, Any]:
    selected: list[dict[str, Any]] = []
    excluded: list[dict[str, str]] = []
    used = 0
    for path in sorted(workspace.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(workspace)
        if any(part in _CONTEXT_EXCLUDED_DIRS for part in relative.parts):
            excluded.append({"path": relative.as_posix(), "reason": "excluded directory"})
            continue
        if any(pattern.search(path.name) for pattern in _SENSITIVE_NAME_PATTERNS):
            excluded.append({"path": relative.as_posix(), "reason": "sensitive filename"})
            continue
        try:
            raw = path.read_bytes()
        except OSError as exc:
            excluded.append({"path": relative.as_posix(), "reason": f"read failed: {type(exc).__name__}"})
            continue
        digest = _sha_bytes(raw)
        if len(raw) > max_file_bytes:
            excluded.append({"path": relative.as_posix(), "reason": "file exceeds context file budget", "sha256": digest})
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            excluded.append({"path": relative.as_posix(), "reason": "binary or non-UTF-8", "sha256": digest})
            continue
        if _SENSITIVE_CONTENT.search(text):
            excluded.append({"path": relative.as_posix(), "reason": "potential secret content", "sha256": digest})
            continue
        if len(selected) >= max_files or used + len(raw) > max_bytes:
            excluded.append({"path": relative.as_posix(), "reason": "context bundle budget exhausted", "sha256": digest})
            continue
        selected.append(
            {
                "path": relative.as_posix(),
                "sha256": digest,
                "bytes": len(raw),
                "content": text,
                "selectionReason": "small text file in authorized disposable workspace",
            }
        )
        used += len(raw)
    return {
        "selected": selected,
        "excluded": excluded,
        "budget": {"maxFiles": max_files, "maxBytes": max_bytes, "maxFileBytes": max_file_bytes, "usedBytes": used},
    }


def make_worker_packet(*, session_id: str, task_id: str) -> dict[str, Any]:
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
    packet = {
        "schemaVersion": "si.worker_packet.v2",
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
            "title": task["title"],
            "tags": task.get("tags", []),
            "acceptanceRefs": task.get("acceptanceRefs", []),
            "status": task["status"],
            "attempts": task.get("attempts", []),
            "authorized_checkpoint_id": task.get("authorized_checkpoint_id"),
            "authorized_intent_hash": task.get("authorized_intent_hash"),
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
        "contextBundle": _context_bundle(workspace),
        "requiredOutput": {
            "type": "object",
            "required": ["producer", "files"],
            "producerRequired": ["adapterId", "surface", "generatedAt"],
            "files": "object mapping safe relative paths to UTF-8 text content",
            "notes": "Do not include commands, secrets, absolute paths, or changes outside the bounded task.",
        },
    }
    event = LS.record_event(
        session,
        "worker.packet_exported",
        {
            "packetId": packet["packetId"],
            "taskId": task_id,
            "selectedContextFiles": len(packet["contextBundle"]["selected"]),
            "authorized_checkpoint_id": packet["authorized_checkpoint_id"],
            "authorized_intent_hash": packet["authorized_intent_hash"],
        },
    )
    packet["eventId"] = event["eventId"]
    LS.save_session(session)
    return packet


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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


def validate_plan(plan: dict[str, Any]) -> None:
    tasks = plan.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise EngineError("plan.tasks must be a non-empty list")
    seen: set[str] = set()
    for index, task in enumerate(tasks):
        if not isinstance(task, dict):
            raise EngineError(f"plan task {index} must be an object")
        key = task.get("key")
        title = task.get("title")
        if not isinstance(key, str) or not key.strip():
            raise EngineError(f"plan task {index} missing key")
        if key in seen:
            raise EngineError(f"duplicate plan task key: {key}")
        seen.add(key)
        if not isinstance(title, str) or not title.strip():
            raise EngineError(f"plan task {key} missing title")
        for field in ("dependencies", "tags", "invalidationConditions", "acceptanceRefs"):
            if field in task and (
                not isinstance(task[field], list) or not all(isinstance(v, str) for v in task[field])
            ):
                raise EngineError(f"plan task {key}.{field} must be a list of strings")
    for task in tasks:
        unknown = sorted(set(task.get("dependencies", [])) - seen)
        if unknown:
            raise EngineError(f"plan task {task['key']} has unknown dependencies: {', '.join(unknown)}")


def add_plan_tasks(session: dict[str, Any], plan: dict[str, Any]) -> dict[str, str]:
    try:
        CP.require_authorized_checkpoint(session)
    except CP.CheckpointError as exc:
        raise EngineError(str(exc)) from exc
    validate_plan(plan)
    existing = {
        task.get("metadata", {}).get("planKey"): task["taskId"]
        for task in session["queue"].values()
        if task.get("metadata", {}).get("planKey")
        and task.get("status") not in {"cancelled", "invalidated"}
        and not task.get("tainted")
    }
    key_to_id = dict(existing)
    pending_specs: list[dict[str, Any]] = []
    for spec in plan["tasks"]:
        if spec["key"] in existing:
            continue
        pending_specs.append(spec)
        # Reserve IDs only by ordering dependencies after creation; plans are
        # required to list dependencies before dependents for deterministic
        # evidence. This makes bad plans fail closed.
        unresolved = [dep for dep in spec.get("dependencies", []) if dep not in key_to_id]
        if unresolved:
            raise EngineError(
                f"plan is not dependency ordered; {spec['key']} precedes {', '.join(unresolved)}"
            )
        task = LS.add_task(
            session,
            title=spec["title"],
            queue=spec.get("queue", "ready"),
            dependencies=[key_to_id[dep] for dep in spec.get("dependencies", [])],
            tags=spec.get("tags", []),
            acceptance_refs=spec.get("acceptanceRefs", []),
            invalidation_conditions=spec.get("invalidationConditions", []),
            operation=spec.get("operation"),
            metadata={
                "planKey": spec["key"],
                "kind": spec.get("kind", "worker"),
                **dict(spec.get("metadata", {})),
            },
        )
        key_to_id[spec["key"]] = task["taskId"]
    LS.record_event(
        session,
        "plan.tasks_added",
        {
            "planId": plan.get("planId"),
            "taskKeys": [spec["key"] for spec in pending_specs],
            "authorized_checkpoint_id": session.get("authorizedCheckpointId"),
            "authorized_intent_hash": session.get("authorizedIntentHash"),
        },
    )
    CP.receipt(
        session,
        action="plan.tasks_add",
        details={"planId": plan.get("planId"), "taskKeys": [spec["key"] for spec in pending_specs]},
    )
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
    if not pending:
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
        validate_plan(plan)
        session["pendingPlan"] = plan
    if auto_approve:
        checkpoint = CP.current_checkpoint(session)
        if not checkpoint:
            raise EngineError("missing initial checkpoint")
        CP.approve_checkpoint(session, checkpoint["checkpoint_id"])
        workspace_path.mkdir(parents=True, exist_ok=True)
        _apply_pending_plan(session)
    LS.save_session(session)
    return session


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
    if plan is not None:
        validate_plan(plan)
        session["pendingPlan"] = plan
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
    LS.save_session(session)
    return session, result


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
    checkpoint is approved.
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
        validate_plan(replacement_plan)
        session["pendingPlan"] = replacement_plan
        LS.record_event(
            session,
            "plan.pending_after_correction",
            {"planId": replacement_plan.get("planId"), "note": "not authoritative until checkpoint approve"},
        )
        LS.save_session(session)
    return session, result

def validate_worker_artifact(artifact: dict[str, Any]) -> None:
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


def apply_worker_artifact(
    *,
    session_id: str,
    task_id: str,
    artifact: dict[str, Any],
) -> dict[str, Any]:
    validate_worker_artifact(artifact)
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
    if task["status"] not in {"ready", "repairing"}:
        raise EngineError(f"task is not executable: {task['status']}")
    ok, reason = LS.transition_task(session, task_id, "running")
    if not ok:
        raise EngineError(reason)

    guard = _guard(session)
    workspace = Path(session["workspace"]).resolve()
    written: list[dict[str, Any]] = []
    try:
        for relative_name, content in artifact["files"].items():
            relative = _safe_relative(relative_name)
            target = workspace / relative
            decision, evidence = guarded_write_text(
                target,
                content,
                guard=guard,
                session_id=session_id,
                task_id=task_id,
            )
            LS.record_policy_decision(session, decision)
            record = {
                "artifactId": evidence["evidenceId"],
                "taskId": task_id,
                "artifactType": "file",
                "relativePath": relative.as_posix(),
                "absolutePath": str(target),
                "sha256": evidence["sha256"],
                "bytes": evidence["bytes"],
                "producer": artifact["producer"],
                "createdAt": evidence["timestamp"],
                "authorized_checkpoint_id": session.get("authorizedCheckpointId"),
                "authorized_intent_hash": session.get("authorizedIntentHash"),
            }
            LS.record_artifact(session, record)
            written.append(record)
    except PolicyDenied as exc:
        LS.record_policy_decision(session, exc.decision)
        LS.transition_task(session, task_id, "failed", reason=exc.decision["reason"])
        LS.save_session(session)
        raise

    task["attempts"].append(
        {
            "attemptId": f"attempt-{len(task['attempts']) + 1}",
            "type": "structured_worker_artifact",
            "producer": artifact["producer"],
            "fileArtifactIds": [record["artifactId"] for record in written],
            "timestamp": _now(),
            "authorized_checkpoint_id": session.get("authorizedCheckpointId"),
            "authorized_intent_hash": session.get("authorizedIntentHash"),
        }
    )
    ok, reason = LS.transition_task(session, task_id, "verifying")
    if not ok:
        raise EngineError(reason)
    CP.receipt(session, action="filesystem.write", details={"taskId": task_id, "files": [w["relativePath"] for w in written]})
    LS.save_session(session)
    return {"session": session, "written": written}


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
    *,
    session_id: str,
    task_id: str,
    command: dict[str, Any],
) -> dict[str, Any]:
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
    workspace = Path(session["workspace"]).resolve()
    argv, cwd = _normalize_command(command, workspace)
    guard = _guard(session)
    try:
        decision, evidence = guarded_run(
            argv,
            cwd=cwd,
            guard=guard,
            session_id=session_id,
            task_id=task_id,
        )
    except PolicyDenied as exc:
        LS.record_policy_decision(session, exc.decision)
        LS.transition_task(session, task_id, "failed", reason=exc.decision["reason"])
        LS.save_session(session)
        raise
    LS.record_policy_decision(session, decision)
    evidence = dict(evidence)
    evidence["authorized_checkpoint_id"] = session.get("authorizedCheckpointId")
    evidence["authorized_intent_hash"] = session.get("authorizedIntentHash")
    LS.record_command(session, evidence)
    passed = evidence["exitCode"] == 0
    verification = LS.record_verification(session, task_id, evidence["evidenceId"], passed)
    verification["authorized_checkpoint_id"] = session.get("authorizedCheckpointId")
    verification["authorized_intent_hash"] = session.get("authorizedIntentHash")
    repair_task: dict[str, Any] | None = None
    if passed:
        ok, reason = LS.transition_task(session, task_id, "complete")
        if not ok:
            raise EngineError(reason)
    else:
        ok, reason = LS.transition_task(session, task_id, "repairing", reason="verification command failed")
        if not ok:
            raise EngineError(reason)
        repair_task = LS.add_task(
            session,
            title=f"Repair: {task['title']}",
            queue="repair",
            dependencies=[],
            tags=list(task.get("tags", [])) + ["repair"],
            acceptance_refs=list(task.get("acceptanceRefs", [])),
            invalidation_conditions=list(task.get("invalidationConditions", [])),
            metadata={
                "kind": "repair",
                "originalTaskId": task_id,
                "verificationCommand": command,
                "failureEvidenceId": evidence["evidenceId"],
            },
        )
    CP.receipt(session, action="process.run", details={"taskId": task_id, "passed": passed})
    LS.save_session(session)
    return {
        "session": session,
        "passed": passed,
        "verification": verification,
        "commandEvidence": evidence,
        "repairTask": repair_task,
    }


def verify_repair(
    *,
    session_id: str,
    repair_task_id: str,
    command: dict[str, Any],
) -> dict[str, Any]:
    result = verify_task(session_id=session_id, task_id=repair_task_id, command=command)
    if not result["passed"]:
        return result
    session = result["session"]
    repair_task = session["queue"][repair_task_id]
    original_id = repair_task.get("metadata", {}).get("originalTaskId")
    if original_id and session["queue"].get(original_id, {}).get("status") == "repairing":
        ok, reason = LS.transition_task(session, original_id, "complete", reason=f"repair task {repair_task_id} passed verification")
        if not ok:
            raise EngineError(reason)
    session["completionEvidence"].append(
        {
            "completionId": f"complete-{len(session['completionEvidence']) + 1}",
            "timestamp": _now(),
            "repairTaskId": repair_task_id,
            "verificationId": result["verification"]["verificationId"],
            "commandEvidenceId": result["commandEvidence"]["evidenceId"],
        }
    )
    LS.save_session(session)
    result["session"] = session
    return result


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
    except (EngineError, ValueError, OSError, json.JSONDecodeError) as exc:
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
    except (EngineError, ValueError, OSError, json.JSONDecodeError) as exc:
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
    except (EngineError, ValueError, OSError) as exc:
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


def cmd_interrupt(args: argparse.Namespace) -> int:
    try:
        structured = _load_json(args.intent_override) if args.intent_override else None
        session, result = interrupt_project(
            session_id=args.session,
            correction=args.correction,
            structured_intent=structured,
            disliked_checkpoint_id=args.checkpoint,
        )
    except (EngineError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc), "code": "interrupt_failed"}))
        return 2
    print(
        json.dumps(
            {
                "sessionId": session["sessionId"],
                **{k: v for k, v in result.items() if k != "newCheckpoint"},
                "newCheckpoint": CP.checkpoint_public_view(result["newCheckpoint"]),
                "state": LS.global_state(session),
                "executionLocked": session.get("executionLocked"),
                "mutationFrozen": session.get("mutationFrozen"),
                "queue": list(session["queue"].values()),
            },
            indent=2,
        )
    )
    return 0


def cmd_correct(args: argparse.Namespace) -> int:
    try:
        replacement = _load_json(args.plan) if args.plan else None
        structured = _load_json(args.intent_override) if args.intent_override else None
        session, result = correct_project(
            session_id=args.session,
            correction=args.correction,
            replacement_plan=replacement,
            structured_intent=structured,
        )
    except (EngineError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc), "code": "correction_failed"}))
        return 2
    print(
        json.dumps(
            {
                "sessionId": session["sessionId"],
                **{k: v for k, v in result.items() if k != "newCheckpoint"},
                "newCheckpoint": CP.checkpoint_public_view(result["newCheckpoint"]) if result.get("newCheckpoint") else None,
                "state": LS.global_state(session),
                "executionLocked": session.get("executionLocked"),
                "mutationFrozen": session.get("mutationFrozen"),
                "pendingPlan": bool(session.get("pendingPlan")),
                "queue": list(session["queue"].values()),
            },
            indent=2,
        )
    )
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    try:
        artifact = _load_json(args.artifact)
        result = apply_worker_artifact(session_id=args.session, task_id=args.task, artifact=artifact)
    except PolicyDenied as exc:
        print(json.dumps({"error": str(exc), "decision": exc.decision, "code": "policy_denied"}, indent=2))
        return 3
    except (EngineError, ValueError, OSError, json.JSONDecodeError) as exc:
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
    except (EngineError, ValueError, OSError, json.JSONDecodeError) as exc:
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
    except (EngineError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc), "code": "repair_verify_failed"}))
        return 2
    print(json.dumps({"sessionId": args.session, "passed": result["passed"], "commandEvidence": result["commandEvidence"], "state": LS.global_state(result["session"])}, indent=2))
    return 0 if result["passed"] else 5


def cmd_authorize(args: argparse.Namespace) -> int:
    try:
        action = _load_json(args.action)
        decision = authorize_only(session_id=args.session, task_id=args.task, action=action)
    except (EngineError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc), "code": "authorization_failed"}))
        return 2
    print(json.dumps(decision, indent=2))
    return 0 if decision["allowed"] else 3


def cmd_packet(args: argparse.Namespace) -> int:
    try:
        packet = make_worker_packet(session_id=args.session, task_id=args.task)
        if args.output:
            output = Path(args.output).expanduser().resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(packet, indent=2), encoding="utf-8")
    except (EngineError, ValueError, OSError) as exc:
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


# Compatibility aliases for the evolved Platynum plan/build contract. They no
# longer impose a global provider key. ``plan`` creates the authoritative
# session and returns the bounded worker task; ``build`` requires a validated
# worker artifact and applies it through the same policy/evidence path.
def cmd_plan(args: argparse.Namespace) -> int:
    class Compat:
        request = args.idea
        workspace = args.workspace
        canonical_root = args.canonical_root
        plan = args.plan
        intent_override = None
        auto_approve = True  # compatibility path still needs an executable session
    return cmd_start(Compat())


def cmd_build(args: argparse.Namespace) -> int:
    session = LS.load_session(args.session)
    if not session:
        print(json.dumps({"error": "invalid or expired session", "code": "invalid_session"}))
        return 4
    task = _first_ready_worker(session)
    if not task:
        print(json.dumps({"error": "no ready worker task", "code": "no_ready_task"}))
        return 4
    if not args.artifact:
        packet = make_worker_packet(session_id=session["sessionId"], task_id=task["taskId"])
        print(
            json.dumps(
                {
                    "sessionId": session["sessionId"],
                    "code": "worker_input_required",
                    "task": task,
                    "workerPacket": packet,
                    "humanActions": [],
                    "state": LS.global_state(session),
                    "note": "Send this provider-neutral packet to any available user intelligence surface and return the validated artifact.",
                },
                indent=2,
            )
        )
        return 3
    class ApplyCompat:
        session = args.session
        task = task["taskId"]
        artifact = args.artifact
    return cmd_apply(ApplyCompat())


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
    correct.add_argument("--plan", help="Pending plan only; not authoritative until approve")
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
