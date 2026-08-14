#!/usr/bin/env python3
"""Execution-lock checkpoints and atomic interruption for Selective Intelligence.

Model interpretation is a proposal. An approved checkpoint is authority.
No plan task, discovery mutation, model worker, filesystem write, Git, or
external call may proceed until an approved checkpoint version exists.
"""
from __future__ import annotations

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
    intent = dict(active_intent or session.get("activeIntent") or {})
    version = int(session.get("checkpointVersion", 0)) + 1
    checkpoint = {
        "schemaVersion": CHECKPOINT_SCHEMA,
        "checkpoint_id": _id("cp"),
        "session_id": session["sessionId"],
        "version": version,
        "intent_summary": intent.get("product_intent") or session.get("objective") or "",
        "scope": list(intent.get("scope") or ([intent.get("product_intent")] if intent.get("product_intent") else [])),
        "non_goals": list(intent.get("non_goals") or intent.get("superseded_concepts") or []),
        "constraints": list(intent.get("constraints") or []),
        "prohibitions": list(intent.get("prohibitions") or []),
        "planned_next_actions": list(planned_next_actions or intent.get("process_directives") or []),
        "evidence_basis": list(evidence_basis or []),
        "intent_hash": compute_intent_hash(intent),
        "status": status,
        "user_decision": None,
        "supersedes_checkpoint_id": supersedes_checkpoint_id,
        "created_at": _now(),
        "active_intent_snapshot": intent,
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


def authorized_checkpoint(session: dict[str, Any]) -> dict[str, Any] | None:
    cid = session.get("authorizedCheckpointId")
    if not cid:
        return None
    checkpoint = get_checkpoint(session, cid)
    if not checkpoint or checkpoint.get("status") != "approved":
        return None
    if checkpoint.get("intent_hash") != session.get("authorizedIntentHash"):
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
    payload = dict(payload)
    payload["authorized_checkpoint_id"] = checkpoint["checkpoint_id"]
    payload["authorized_intent_hash"] = checkpoint["intent_hash"]
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
    if obj.get("status") in {"superseded", "disliked", "correction_mode"}:
        raise CheckpointError("object status forbids execution")


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
    prior_intent = dict(session.get("activeIntent") or {})
    session["activeIntent"] = merge_active_contract(session.get("activeIntent"), intent_event)
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
        disliked_checkpoint_id=session.get("authorizedCheckpointId") or session.get("currentCheckpointId"),
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
    """Stable public fields for product wiring (Platynum dislike → SI interrupt)."""
    return {
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
    }
