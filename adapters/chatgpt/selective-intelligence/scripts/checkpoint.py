#!/usr/bin/env python3
"""Execution-lock checkpoints and atomic interruption for Selective Intelligence.

Model interpretation is a proposal. An approved checkpoint is authority.
No plan task, discovery mutation, model worker, filesystem write, Git, or
external call may proceed until an approved checkpoint version exists.
"""
from __future__ import annotations

import copy
import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from intent_contract import INTENT_OPERATIONS, classify_intent, intent_hash, merge_active_contract

CHECKPOINT_SCHEMA = "si.checkpoint.v1"
CHECKPOINT_STATUSES = {
    "proposed",
    "approved",
    "rejected",
    "superseded",
    "interrupted",
    "correction_mode",
}
EXECUTABLE_STATUSES = {"approved"}
SIDE_EFFECT_KINDS = {
    "filesystem.write",
    "filesystem.delete",
    "git.mutation",
    "process.run",
    "network.call",
    "deploy",
    "plan.tasks_add",
    "discovery.mutate",
    "worker.dispatch",
}


class CheckpointError(RuntimeError):
    """Fail-closed checkpoint / interrupt violation."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


# Only execution progress is mutable under an existing task approval. Unknown
# fields remain part of the contract so new instruction fields fail closed.
_TASK_RUNTIME_FIELDS = frozenset({
    "status", "attempts", "createdAt", "updatedAt", "completedAt",
    "invalidatedByEventId", "invalidationReason", "tainted", "cancelRequested",
    "statusReasons", "activeVerification",
})


def _material_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _execution_scope(session: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy({key: session.get(key) for key in (
        "workspace", "canonicalRoots", "writableRoots",
    )})


def _task_material(task: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy({key: value for key, value in task.items()
                          if key not in _TASK_RUNTIME_FIELDS})


def _assert_task_content(session: dict[str, Any], obj: dict[str, Any]) -> None:
    task_id = obj.get("taskId")
    if not task_id:
        return
    checkpoint = authorized_checkpoint(session)
    binding = (checkpoint or {}).get("task_content_bindings", {}).get(task_id)
    if not isinstance(binding, dict) or not isinstance(binding.get("snapshot"), dict):
        raise CheckpointError("missing task content snapshot; reconcile before execution")
    expected = binding.get("hash")
    if not expected or _material_hash(binding["snapshot"]) != expected:
        raise CheckpointError("task content snapshot changed; reconcile before execution")
    owner = session.get("queue", {}).get(task_id)
    if owner is None:
        # Sparse bound work objects are supported, but a returned file result
        # cannot stand in for the authoritative task that it claims to answer.
        if "files" in obj or "producer" in obj:
            raise CheckpointError("returned work has no authoritative task")
        owner = obj
    if _material_hash(_task_material(owner)) != expected:
        raise CheckpointError("task content changed after authorization; reconcile before execution")
    if obj is not owner and "files" not in obj and ("title" in obj or "queue" in obj):
        if _material_hash(_task_material(obj)) != expected:
            raise CheckpointError("work object differs from the authorized task content")


def compute_intent_hash(active_intent: dict[str, Any]) -> str:
    return intent_hash(active_intent)


def emit_checkpoint(
    session: dict[str, Any],
    *,
    active_intent: dict[str, Any] | None = None,
    evidence_basis: list[str] | None = None,
    planned_next_actions: list[str] | None = None,
    supersedes_checkpoint_id: str | None = None,
    status: str = "proposed",
) -> dict[str, Any]:
    """Emit a versioned intent checkpoint. Status defaults to proposed (not authority)."""
    if status not in CHECKPOINT_STATUSES:
        raise CheckpointError(f"invalid checkpoint status: {status}")
    source = active_intent if active_intent is not None else session.get("activeIntent")
    if source is None:
        # Legacy callers without a contract may propose their original objective.
        # An explicit empty corrected contract must never restore that objective.
        source = {"product_intent": session.get("objective") or ""}
    if not isinstance(source, dict):
        raise CheckpointError("active intent must be an object")
    intent = copy.deepcopy(source)
    version = int(session.get("checkpointVersion", 0)) + 1
    checkpoint = {
        "schemaVersion": CHECKPOINT_SCHEMA,
        "checkpoint_id": _id("cp"),
        "session_id": session["sessionId"],
        "version": version,
        "intent_summary": intent.get("product_intent") or "",
        "scope": list(intent.get("scope") or ([intent.get("product_intent")] if intent.get("product_intent") else [])),
        "non_goals": list(intent.get("non_goals") or intent.get("superseded_concepts") or []),
        "constraints": list(intent.get("constraints") or []),
        "prohibitions": list(intent.get("prohibitions") or []),
        "planned_next_actions": list(
            planned_next_actions if planned_next_actions is not None
            else intent.get("process_directives") or []
        ),
        "evidence_basis": list(evidence_basis or []),
        "intent_hash": compute_intent_hash(intent),
        "status": status,
        "user_decision": None,
        "supersedes_checkpoint_id": supersedes_checkpoint_id,
        "created_at": _now(),
        "active_intent_snapshot": intent,
        "execution_scope_snapshot": _execution_scope(session),
        "execution_scope_hash": _material_hash(_execution_scope(session)),
        "task_content_bindings": {},
        "generation_authority": status == "approved",
        "mutation_frozen": status != "approved",
    }
    session.setdefault("checkpoints", []).append(checkpoint)
    session["checkpointVersion"] = version
    session["currentCheckpointId"] = checkpoint["checkpoint_id"]
    if status == "approved":
        session["authorizedCheckpointId"] = checkpoint["checkpoint_id"]
        session["authorizedIntentHash"] = checkpoint["intent_hash"]
        session["executionLocked"] = False
        session["mutationFrozen"] = False
        session["correctionMode"] = False
        session["generationAuthority"] = True
    else:
        # Proposed / interrupted / rejected checkpoints are not authority.
        session["generationAuthority"] = False
        session["executionLocked"] = True
        session["mutationFrozen"] = True
        if status in {"interrupted", "correction_mode", "rejected"}:
            session["authorizedCheckpointId"] = None
            session["authorizedIntentHash"] = None
    session.setdefault("events", []).append(
        {
            "eventId": _id("evt"),
            "eventType": "checkpoint.emitted",
            "timestamp": _now(),
            "actor": "si",
            "payload": {
                "checkpoint_id": checkpoint["checkpoint_id"],
                "version": version,
                "status": status,
                "intent_hash": checkpoint["intent_hash"],
            },
        }
    )
    return checkpoint


def get_checkpoint(session: dict[str, Any], checkpoint_id: str) -> dict[str, Any] | None:
    for checkpoint in session.get("checkpoints", []):
        if checkpoint["checkpoint_id"] == checkpoint_id:
            return checkpoint
    return None


def current_checkpoint(session: dict[str, Any]) -> dict[str, Any] | None:
    cid = session.get("currentCheckpointId")
    if not cid:
        return None
    return get_checkpoint(session, cid)


def _assert_current_intent(session: dict[str, Any], checkpoint: dict[str, Any]) -> None:
    """Check actual intent material, not two copies of a cached hash.

    Old checkpoints whose previously unhashed assumptions/refinements changed
    must be reconciled rather than silently inheriting execution authority.
    No actor, adapter, or checkpoint flag is a replacement for this comparison.
    """
    if checkpoint.get("session_id") != session.get("sessionId"):
        raise CheckpointError("checkpoint belongs to a different session")
    if checkpoint.get("checkpoint_id") != session.get("currentCheckpointId"):
        raise CheckpointError("checkpoint is no longer current")
    snapshot = checkpoint.get("active_intent_snapshot")
    active = session.get("activeIntent")
    if not isinstance(snapshot, dict) or not isinstance(active, dict):
        raise CheckpointError("missing authoritative intent snapshot; reconcile before execution")
    expected = checkpoint.get("intent_hash")
    if not expected or compute_intent_hash(snapshot) != expected:
        raise CheckpointError("checkpoint intent snapshot changed; reconcile before execution")
    if compute_intent_hash(active) != expected:
        raise CheckpointError("active intent changed after checkpoint; reconcile before execution")
    if checkpoint.get("intent_summary") != (snapshot.get("product_intent") or ""):
        raise CheckpointError("checkpoint summary differs from its intent snapshot")
    scope = checkpoint.get("execution_scope_snapshot")
    if not isinstance(scope, dict) or _material_hash(scope) != checkpoint.get("execution_scope_hash"):
        raise CheckpointError("missing or changed execution scope snapshot; reconcile before execution")
    if _execution_scope(session) != scope:
        raise CheckpointError("execution scope changed after checkpoint; reconcile before execution")


def authorized_checkpoint(session: dict[str, Any]) -> dict[str, Any] | None:
    cid = session.get("authorizedCheckpointId")
    if not cid:
        return None
    checkpoint = get_checkpoint(session, cid)
    if not checkpoint or checkpoint.get("status") != "approved":
        return None
    if checkpoint.get("intent_hash") != session.get("authorizedIntentHash"):
        return None
    if session.get("generationAuthority") is not True or checkpoint.get("generation_authority") is not True:
        return None
    try:
        _assert_current_intent(session, checkpoint)
    except CheckpointError:
        return None
    return checkpoint


def approve_checkpoint(
    session: dict[str, Any],
    checkpoint_id: str,
    *,
    actor: str = "user",
    expected_intent_hash: str | None = None,
) -> dict[str, Any]:
    checkpoint = get_checkpoint(session, checkpoint_id)
    if not checkpoint:
        raise CheckpointError("checkpoint not found")
    if session.get("currentCheckpointId") != checkpoint_id:
        raise CheckpointError("stale checkpoint; only currentCheckpointId may be approved")
    if expected_intent_hash is not None and expected_intent_hash != checkpoint.get("intent_hash"):
        raise CheckpointError("stale authorized_intent_hash; fail closed")
    if checkpoint["status"] not in {"proposed", "correction_mode"}:
        raise CheckpointError(f"checkpoint cannot be approved from status {checkpoint['status']}")
    _assert_current_intent(session, checkpoint)
    # Supersede any previously approved checkpoint.
    for prior in session.get("checkpoints", []):
        if prior["status"] == "approved" and prior["checkpoint_id"] != checkpoint_id:
            prior["status"] = "superseded"
            prior["user_decision"] = prior.get("user_decision") or "superseded"
    checkpoint["status"] = "approved"
    checkpoint["user_decision"] = "approve"
    checkpoint["generation_authority"] = True
    checkpoint["mutation_frozen"] = False
    checkpoint["approved_at"] = _now()
    session["authorizedCheckpointId"] = checkpoint_id
    session["authorizedIntentHash"] = checkpoint["intent_hash"]
    session["executionLocked"] = False
    session["mutationFrozen"] = False
    session["correctionMode"] = False
    session["generationAuthority"] = True
    session.setdefault("events", []).append(
        {
            "eventId": _id("evt"),
            "eventType": "checkpoint.approved",
            "timestamp": _now(),
            "actor": actor,
            "payload": {"checkpoint_id": checkpoint_id, "intent_hash": checkpoint["intent_hash"]},
        }
    )
    return checkpoint


def reject_checkpoint(
    session: dict[str, Any],
    checkpoint_id: str,
    *,
    reason: str | None = None,
    actor: str = "user",
) -> dict[str, Any]:
    checkpoint = get_checkpoint(session, checkpoint_id)
    if not checkpoint:
        raise CheckpointError("checkpoint not found")
    if session.get("currentCheckpointId") != checkpoint_id:
        raise CheckpointError("stale checkpoint; only currentCheckpointId may be rejected")
    checkpoint["status"] = "rejected"
    checkpoint["user_decision"] = "reject"
    checkpoint["generation_authority"] = False
    checkpoint["mutation_frozen"] = True
    checkpoint["rejection_reason"] = reason
    session["authorizedCheckpointId"] = None
    session["authorizedIntentHash"] = None
    session["executionLocked"] = True
    session["mutationFrozen"] = True
    session["generationAuthority"] = False
    session.setdefault("events", []).append(
        {
            "eventId": _id("evt"),
            "eventType": "checkpoint.rejected",
            "timestamp": _now(),
            "actor": actor,
            "payload": {"checkpoint_id": checkpoint_id, "reason": reason},
        }
    )
    return checkpoint


def require_authorized_checkpoint(
    session: dict[str, Any],
    *,
    expected_checkpoint_id: str | None = None,
    expected_intent_hash: str | None = None,
    allow_side_effect: bool = True,
) -> dict[str, Any]:
    """Fail closed unless an approved, non-stale checkpoint authorizes work."""
    if session.get("siActive") is not True or session.get("governanceMode") != "always_on_after_activation":
        raise CheckpointError("Selective Intelligence governance is not active; execution denied")
    if session.get("correctionMode") or session.get("mutationFrozen"):
        raise CheckpointError("session is in correction/interrupt mode; side effects denied")
    if session.get("executionLocked"):
        raise CheckpointError("no approved checkpoint; execution remains locked")
    checkpoint = authorized_checkpoint(session)
    if not checkpoint:
        raise CheckpointError("no authorized approved checkpoint")
    if expected_checkpoint_id and expected_checkpoint_id != checkpoint["checkpoint_id"]:
        raise CheckpointError("stale or mismatched authorized_checkpoint_id")
    if expected_intent_hash and expected_intent_hash != checkpoint["intent_hash"]:
        raise CheckpointError("stale authorized_intent_hash; fail closed")
    if session.get("authorizedIntentHash") != checkpoint["intent_hash"]:
        raise CheckpointError("session authorized intent hash drifted; fail closed")
    if allow_side_effect and checkpoint["status"] not in EXECUTABLE_STATUSES:
        raise CheckpointError("checkpoint is not approved for side effects")
    return checkpoint


def bind_authorization(session: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """Stamp authorized_checkpoint_id + authorized_intent_hash onto a work object."""
    checkpoint = require_authorized_checkpoint(session)
    payload = copy.deepcopy(payload)
    payload["authorized_checkpoint_id"] = checkpoint["checkpoint_id"]
    payload["authorized_intent_hash"] = checkpoint["intent_hash"]
    task_id = payload.get("taskId")
    if task_id:
        if not isinstance(task_id, str):
            raise CheckpointError("task identity must be a string")
        material = _task_material(payload)
        binding = {"hash": _material_hash(material), "snapshot": material}
        bindings = checkpoint.setdefault("task_content_bindings", {})
        previous = bindings.get(task_id)
        if previous is not None and previous != binding:
            raise CheckpointError("cannot rebind changed task content under the same approval")
        bindings[task_id] = binding
    return payload


def assert_binding(session: dict[str, Any], obj: dict[str, Any]) -> None:
    """Fail closed when a task/packet/artifact carries a stale or missing binding."""
    if session.get("correctionMode") or session.get("mutationFrozen") or session.get("executionLocked"):
        raise CheckpointError("session not authorized for bound work")
    cid = obj.get("authorized_checkpoint_id")
    ihash = obj.get("authorized_intent_hash")
    if not cid or not ihash:
        raise CheckpointError("missing authorized_checkpoint_id / authorized_intent_hash")
    require_authorized_checkpoint(
        session,
        expected_checkpoint_id=cid,
        expected_intent_hash=ihash,
    )
    if session.get("authorizedCheckpointId") != cid:
        raise CheckpointError("object bound to superseded or unapproved checkpoint")
    if obj.get("status") in {"superseded", "disliked", "correction_mode", "cancelled", "invalidated"}:
        raise CheckpointError("object status forbids execution")
    if obj.get("tainted") or obj.get("cancelRequested"):
        raise CheckpointError("tainted or cancellation-requested work cannot execute")
    _assert_task_content(session, obj)


def mark_tainted_effects(
    session: dict[str, Any],
    *,
    rejected_checkpoint_id: str,
    reason: str,
) -> list[str]:
    """Mark completed effects from a rejected checkpoint as potentially tainted."""
    tainted: list[str] = []
    for artifact in session.get("artifacts", []):
        if artifact.get("authorized_checkpoint_id") == rejected_checkpoint_id or (
            not artifact.get("authorized_checkpoint_id") and rejected_checkpoint_id
        ):
            artifact["tainted"] = True
            artifact["taintReason"] = reason
            artifact["taintedAt"] = _now()
            tainted.append(str(artifact.get("artifactId")))
    for task in session.get("queue", {}).values():
        if task.get("status") == "complete" and (
            task.get("authorized_checkpoint_id") == rejected_checkpoint_id
            or task.get("metadata", {}).get("authorized_checkpoint_id") == rejected_checkpoint_id
            or not task.get("authorized_checkpoint_id")
        ):
            task["tainted"] = True
            task["taintReason"] = reason
            task["taintedAt"] = _now()
            # Completed work from a rejected interpretation is not sacred.
            task.setdefault("statusReasons", []).append(
                {"timestamp": _now(), "status": "complete", "reason": f"tainted: {reason}"}
            )
            tainted.append(task["taskId"])
    session.setdefault("taintedEffectIds", [])
    session["taintedEffectIds"] = list(dict.fromkeys(session["taintedEffectIds"] + tainted))
    return tainted


def _cancel_or_request_cancel(session: dict[str, Any], *, reason: str, checkpoint_id: str | None) -> dict[str, Any]:
    cancelled: list[str] = []
    cancel_requested: list[str] = []
    for task in session.get("queue", {}).values():
        bound = task.get("authorized_checkpoint_id") or task.get("metadata", {}).get("authorized_checkpoint_id")
        if checkpoint_id and bound and bound != checkpoint_id:
            continue
        status = task["status"]
        if status in {"pending", "ready", "human_blocked", "failed"}:
            previous = status
            task["status"] = "cancelled"
            task["updatedAt"] = _now()
            task.setdefault("statusReasons", []).append(
                {"timestamp": _now(), "status": "cancelled", "reason": reason}
            )
            cancelled.append(task["taskId"])
            session.setdefault("events", []).append(
                {
                    "eventId": _id("evt"),
                    "eventType": "task.cancelled",
                    "timestamp": _now(),
                    "actor": "si",
                    "payload": {"taskId": task["taskId"], "from": previous, "reason": reason},
                }
            )
        elif status in {"running", "verifying", "repairing"}:
            # Request cancel of in-flight work — do not skip these statuses.
            task["cancelRequested"] = True
            task["cancelRequestedAt"] = _now()
            task["cancelReason"] = reason
            previous = status
            # Best-effort transition to cancelled when the transition table allows it.
            if status == "running":
                task["status"] = "cancelled"
                task["updatedAt"] = _now()
                cancelled.append(task["taskId"])
                session.setdefault("events", []).append(
                    {
                        "eventId": _id("evt"),
                        "eventType": "task.cancelled",
                        "timestamp": _now(),
                        "actor": "si",
                        "payload": {"taskId": task["taskId"], "from": previous, "reason": reason},
                    }
                )
            else:
                # verifying / repairing: request cancel; mark interrupted if complete transition unavailable
                task["status"] = "cancelled"
                task["updatedAt"] = _now()
                cancel_requested.append(task["taskId"])
                cancelled.append(task["taskId"])
                session.setdefault("events", []).append(
                    {
                        "eventId": _id("evt"),
                        "eventType": "task.cancel_requested",
                        "timestamp": _now(),
                        "actor": "si",
                        "payload": {"taskId": task["taskId"], "from": previous, "reason": reason},
                    }
                )
    return {"cancelledTaskIds": cancelled, "cancelRequestedTaskIds": cancel_requested}


def interrupt(
    session: dict[str, Any],
    *,
    correction: str,
    structured_intent: dict[str, Any] | None = None,
    disliked_checkpoint_id: str | None = None,
    actor: str = "user",
) -> dict[str, Any]:
    """Atomic SI session-state interruption.

    Marks generationAuthority false, prevents new tool dispatch under the SI
    session lock, cancels queued work, requests cancel of running/verifying/
    repairing tasks in session state, freezes FS/Git/deploy mutations gated by
    this session, marks completed effects from the rejected checkpoint as
    tainted, captures the correction, and emits a new proposed checkpoint.
    Resume requires approval of the new checkpoint.

    Claim scope: this is an atomic SI *session-state* interrupt. It does not
    by itself prove that an external model generation stream, tool dispatcher,
    or worker process has stopped until a product connection demonstrates that
    those runtimes honor the session flags.
    """
    current_id = session.get("currentCheckpointId")
    if disliked_checkpoint_id and disliked_checkpoint_id != current_id:
        raise CheckpointError("stale checkpoint; dislike applies only to currentCheckpointId")
    rejected_id = disliked_checkpoint_id or session.get("authorizedCheckpointId") or current_id
    if rejected_id:
        checkpoint = get_checkpoint(session, rejected_id)
        if checkpoint and checkpoint["status"] in {"proposed", "approved", "correction_mode"}:
            checkpoint["status"] = "interrupted"
            checkpoint["user_decision"] = "dislike"
            checkpoint["generation_authority"] = False
            checkpoint["mutation_frozen"] = True
            checkpoint["interrupted_at"] = _now()

    session["generationAuthority"] = False
    session["mutationFrozen"] = True
    session["executionLocked"] = True
    session["correctionMode"] = True
    session["authorizedCheckpointId"] = None
    session["authorizedIntentHash"] = None

    # An old pending proposal must not inherit the next checkpoint's approval.
    # Preserve evidence separately; do not reuse or silently rebind the old plan.
    pending_plan = session.pop("pendingPlan", None)
    if pending_plan is not None:
        session.setdefault("invalidatedPlans", []).append({
            "plan": copy.deepcopy(pending_plan),
            "checkpoint_id": rejected_id,
            "reason": "intent correction invalidated the pending plan",
            "invalidated_at": _now(),
        })

    cancel_result = _cancel_or_request_cancel(
        session,
        reason="interrupt: rejected checkpoint interpretation",
        checkpoint_id=rejected_id,
    )
    tainted = mark_tainted_effects(
        session,
        rejected_checkpoint_id=rejected_id or "",
        reason="completed under rejected/interrupted checkpoint",
    )

    intent_event = classify_intent(
        correction,
        event_type="correction",
        structured_override=structured_intent,
    )
    if intent_event.get("operation") not in INTENT_OPERATIONS:
        raise CheckpointError("correction missing intent operation")

    session.setdefault("intentEvents", []).append(intent_event)
    prior_intent = copy.deepcopy(session.get("activeIntent") or {})
    session["activeIntent"] = merge_active_contract(session.get("activeIntent"), intent_event)
    # Consumers such as worker packets must not see the rejected original goal.
    # Raw requests remain in intentEvents and the prior checkpoint snapshots.
    session["objective"] = session["activeIntent"].get("product_intent") or ""
    diff = session["activeIntent"].get("lastOperationDiff") or {}

    new_checkpoint = emit_checkpoint(
        session,
        active_intent=session["activeIntent"],
        evidence_basis=[
            f"interrupt correction: {correction}",
            f"operation: {intent_event.get('operation')}",
            f"supersedes: {rejected_id}",
        ],
        planned_next_actions=[],
        supersedes_checkpoint_id=rejected_id,
        status="proposed",
    )

    result = {
        "interruptedCheckpointId": rejected_id,
        "newCheckpoint": new_checkpoint,
        "intentEvent": intent_event,
        "operation": intent_event.get("operation"),
        "cancelledTaskIds": cancel_result["cancelledTaskIds"],
        "cancelRequestedTaskIds": cancel_result["cancelRequestedTaskIds"],
        "taintedEffectIds": tainted,
        "removed": diff.get("removed") or {},
        "retained": diff.get("retained") or {},
        "changed": diff.get("changed") or {},
        "priorIntentHash": compute_intent_hash(prior_intent) if prior_intent else None,
        "newIntentHash": session["activeIntent"].get("intent_hash"),
        "resumeRequiresApproval": True,
        "mutationFrozen": True,
        "generationAuthority": False,
    }
    session.setdefault("events", []).append(
        {
            "eventId": _id("evt"),
            "eventType": "session.interrupted",
            "timestamp": _now(),
            "actor": actor,
            "payload": {
                "interruptedCheckpointId": rejected_id,
                "newCheckpointId": new_checkpoint["checkpoint_id"],
                "operation": intent_event.get("operation"),
                "cancelledTaskIds": result["cancelledTaskIds"],
                "taintedEffectIds": tainted,
            },
        }
    )
    return result


def compile_correction_transition(
    session: dict[str, Any],
    correction: str,
    *,
    structured_intent: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """SI-owned invariant compiler: correction → canonical state transition.

    Callers may not supply a replacement plan as authority. SI classifies the
    correction, merges via intent operations, and emits a new proposed checkpoint.
    Plan tasks may be attached only after the new checkpoint is approved.
    """
    return interrupt(
        session,
        correction=correction,
        structured_intent=structured_intent,
        disliked_checkpoint_id=session.get("currentCheckpointId"),
    )


def receipt(
    session: dict[str, Any],
    *,
    action: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Action receipt bound to the authorized checkpoint."""
    checkpoint = require_authorized_checkpoint(session)
    record = {
        "receiptId": _id("rcpt"),
        "action": action,
        "timestamp": _now(),
        "authorized_checkpoint_id": checkpoint["checkpoint_id"],
        "authorized_intent_hash": checkpoint["intent_hash"],
        "details": details or {},
    }
    session.setdefault("actionReceipts", []).append(record)
    return record


def side_effect_allowed(session: dict[str, Any], kind: str) -> bool:
    if kind not in SIDE_EFFECT_KINDS:
        return False
    try:
        require_authorized_checkpoint(session)
    except CheckpointError:
        return False
    return True


def checkpoint_public_view(checkpoint: dict[str, Any]) -> dict[str, Any]:
    """Stable detached public fields; views cannot mutate approval evidence."""
    return copy.deepcopy({
        "checkpoint_id": checkpoint["checkpoint_id"],
        "session_id": checkpoint["session_id"],
        "version": checkpoint["version"],
        "intent_summary": checkpoint["intent_summary"],
        "scope": checkpoint["scope"],
        "non_goals": checkpoint["non_goals"],
        "constraints": checkpoint["constraints"],
        "prohibitions": checkpoint["prohibitions"],
        "planned_next_actions": checkpoint["planned_next_actions"],
        "evidence_basis": checkpoint["evidence_basis"],
        "intent_hash": checkpoint["intent_hash"],
        "status": checkpoint["status"],
        "user_decision": checkpoint["user_decision"],
        "supersedes_checkpoint_id": checkpoint["supersedes_checkpoint_id"],
        "created_at": checkpoint["created_at"],
    })
