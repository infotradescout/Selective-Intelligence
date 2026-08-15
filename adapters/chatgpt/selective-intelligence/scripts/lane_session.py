#!/usr/bin/env python3
"""Authoritative SI project/session state with intent and queue reconciliation."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from intent_contract import classify_intent, concept_tokens, merge_active_contract
import checkpoint as CP

try:
    import lane_registry as reg  # type: ignore
except ImportError:  # The first vertical can run without registry manifests.
    reg = None

SCHEMA_VERSION = "si_lane_session.v3"
LANE_STATUSES = {
    "pending", "ready", "running", "waiting_dependency", "verifying", "repairing",
    "human_blocked", "complete", "system_error", "cancelled",
}
TASK_STATUSES = {
    "pending", "ready", "running", "verifying", "repairing", "human_blocked",
    "complete", "failed", "invalidated", "cancelled",
}
ALLOWED_LANE_TRANSITIONS = {
    "pending": {"pending", "ready", "waiting_dependency", "cancelled"},
    "waiting_dependency": {"waiting_dependency", "ready", "cancelled"},
    "ready": {"ready", "running", "human_blocked", "waiting_dependency", "cancelled"},
    "running": {"running", "verifying", "human_blocked", "repairing", "system_error", "cancelled"},
    "verifying": {"verifying", "complete", "repairing", "system_error"},
    "repairing": {"repairing", "running", "human_blocked", "system_error", "complete"},
    "human_blocked": {"human_blocked", "ready", "cancelled"},
    "complete": {"complete"},
    "system_error": {"system_error", "ready", "cancelled"},
    "cancelled": {"cancelled"},
}
ALLOWED_TASK_TRANSITIONS = {
    "pending": {"pending", "ready", "human_blocked", "invalidated", "cancelled"},
    "ready": {"ready", "running", "human_blocked", "invalidated", "cancelled"},
    "running": {"running", "verifying", "repairing", "failed", "human_blocked", "cancelled"},
    "verifying": {"verifying", "complete", "repairing", "failed", "cancelled"},
    "repairing": {"repairing", "running", "verifying", "complete", "failed", "human_blocked", "cancelled"},
    "human_blocked": {"human_blocked", "ready", "invalidated", "cancelled"},
    "failed": {"failed", "repairing", "ready", "invalidated", "cancelled"},
    "complete": {"complete"},
    "invalidated": {"invalidated"},
    "cancelled": {"cancelled"},
}
RUNNABLE_TASKS = {"ready", "running", "verifying", "repairing"}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def sessions_dir() -> Path:
    directory = Path(os.environ.get("SI_SESSION_DIR") or (Path(tempfile.gettempdir()) / "si-build-sessions"))
    directory.mkdir(parents=True, exist_ok=True)
    return directory.resolve()


def session_path(session_id: str) -> Path:
    if not session_id or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for ch in session_id):
        raise ValueError("invalid session id")
    return sessions_dir() / f"{session_id}.session.json"


def save_session(session: dict[str, Any]) -> None:
    session["updatedAt"] = _now()
    target = session_path(session["sessionId"])
    temp = target.with_suffix(f".{uuid.uuid4().hex}.tmp")
    temp.write_text(json.dumps(session, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(temp, target)


def load_session(session_id: str) -> dict[str, Any] | None:
    try:
        path = session_path(session_id)
    except ValueError:
        return None
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schemaVersion") != SCHEMA_VERSION:
        raise ValueError(f"unsupported session schema: {data.get('schemaVersion')}")
    return data


def record_event(session: dict[str, Any], event_type: str, payload: dict[str, Any], *, actor: str = "si") -> dict[str, Any]:
    event = {
        "eventId": _id("evt"),
        "eventType": event_type,
        "timestamp": _now(),
        "actor": actor,
        "payload": payload,
    }
    session.setdefault("events", []).append(event)
    return event


def new_session(
    objective: str,
    *,
    workspace: str | None = None,
    canonical_roots: list[str] | None = None,
    writable_roots: list[str] | None = None,
    structured_intent: dict[str, Any] | None = None,
    emit_initial_checkpoint: bool = True,
) -> dict[str, Any]:
    intent = classify_intent(objective, event_type="request", structured_override=structured_intent)
    active = merge_active_contract(None, intent)
    session: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "sessionId": f"si-{uuid.uuid4().hex}",
        "siActive": True,
        "governanceMode": "always_on_after_activation",
        "objective": objective,
        "workspace": workspace,
        "canonicalRoots": list(canonical_roots or []),
        "writableRoots": list(writable_roots or ([workspace] if workspace else [])),
        "intentEvents": [intent],
        "activeIntent": active,
        "knownFacts": [],
        "assumptions": [],
        "unknowns": [],
        "contradictions": [],
        "capabilityInventory": [],
        "backendSelections": {},
        "queue": {},
        "lanes": {},
        "events": [],
        "policyDecisions": [],
        "commandEvidence": [],
        "artifacts": [],
        "verificationAttempts": [],
        "humanActions": [],
        "completionEvidence": [],
        "checkpoints": [],
        "checkpointVersion": 0,
        "currentCheckpointId": None,
        "authorizedCheckpointId": None,
        "authorizedIntentHash": None,
        "executionLocked": True,
        "mutationFrozen": True,
        "correctionMode": False,
        "generationAuthority": False,
        "taintedEffectIds": [],
        "actionReceipts": [],
        "createdAt": _now(),
        "updatedAt": _now(),
    }
    record_event(session, "session.created", {"intentEventId": intent["eventId"]})
    if emit_initial_checkpoint:
        # Model interpretation is a proposal. Execution stays locked until approve.
        CP.emit_checkpoint(
            session,
            active_intent=active,
            evidence_basis=[f"seed request: {objective}"],
            planned_next_actions=list(active.get("process_directives") or []),
            status="proposed",
        )
    return session


def add_fact(session: dict[str, Any], claim: str, evidence: Any, *, status: str = "confirmed") -> dict[str, Any]:
    fact = {"factId": _id("fact"), "claim": claim, "status": status, "evidence": evidence, "timestamp": _now()}
    session["knownFacts"].append(fact)
    record_event(session, "fact.recorded", {"factId": fact["factId"], "status": status})
    return fact


def add_task(
    session: dict[str, Any],
    *,
    title: str,
    queue: str,
    dependencies: list[str] | None = None,
    tags: list[str] | None = None,
    intent_refs: list[str] | None = None,
    acceptance_refs: list[str] | None = None,
    invalidation_conditions: list[str] | None = None,
    operation: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    require_checkpoint: bool = True,
) -> dict[str, Any]:
    if require_checkpoint:
        CP.require_authorized_checkpoint(session)
    task_id = _id("task")
    auth = {
        "authorized_checkpoint_id": session.get("authorizedCheckpointId"),
        "authorized_intent_hash": session.get("authorizedIntentHash"),
    }
    meta = dict(metadata or {})
    meta.update({k: v for k, v in auth.items() if v})
    task = {
        "taskId": task_id,
        "title": title,
        "queue": queue,
        "status": "pending",
        "dependencies": list(dependencies or []),
        "tags": list(tags or []),
        "intentRefs": list(intent_refs or session["activeIntent"].get("sourceEventIds", [])),
        "acceptanceRefs": list(acceptance_refs or []),
        "invalidationConditions": list(invalidation_conditions or []),
        "operation": operation,
        "metadata": meta,
        "authorized_checkpoint_id": auth["authorized_checkpoint_id"],
        "authorized_intent_hash": auth["authorized_intent_hash"],
        "attempts": [],
        "createdAt": _now(),
        "updatedAt": _now(),
        "completedAt": None,
        "invalidatedByEventId": None,
        "invalidationReason": None,
        "tainted": False,
        "cancelRequested": False,
    }
    session["queue"][task_id] = task
    record_event(
        session,
        "task.created",
        {
            "taskId": task_id,
            "title": title,
            "queue": queue,
            "authorized_checkpoint_id": auth["authorized_checkpoint_id"],
            "authorized_intent_hash": auth["authorized_intent_hash"],
        },
    )
    recompute_task_readiness(session)
    return task


def transition_task(session: dict[str, Any], task_id: str, status: str, *, reason: str | None = None) -> tuple[bool, str]:
    task = session["queue"].get(task_id)
    if not task:
        return False, "task not found"
    if status not in TASK_STATUSES:
        return False, f"invalid task status: {status}"
    # Side-effecting progress requires an authorized checkpoint binding.
    if status in {"running", "verifying", "repairing"} and not session.get("correctionMode"):
        try:
            CP.assert_binding(session, task)
        except CP.CheckpointError as exc:
            return False, str(exc)
    current = task["status"]
    if status not in ALLOWED_TASK_TRANSITIONS.get(current, set()):
        return False, f"illegal task transition {current} -> {status}"
    task["status"] = status
    task["updatedAt"] = _now()
    if reason:
        task.setdefault("statusReasons", []).append({"timestamp": _now(), "status": status, "reason": reason})
    if status == "complete":
        task["completedAt"] = _now()
    record_event(session, "task.transition", {"taskId": task_id, "from": current, "to": status, "reason": reason})
    recompute_task_readiness(session)
    return True, "ok"


def recompute_task_readiness(session: dict[str, Any]) -> None:
    queue = session.get("queue", {})
    for task in queue.values():
        if task["status"] != "pending":
            continue
        dependencies = [queue.get(dep) for dep in task.get("dependencies", [])]
        if all(dep and dep.get("status") == "complete" for dep in dependencies):
            task["status"] = "ready"
            task["updatedAt"] = _now()


def ready_tasks(session: dict[str, Any]) -> list[dict[str, Any]]:
    recompute_task_readiness(session)
    return [task for task in session["queue"].values() if task["status"] == "ready"]


def add_correction(
    session: dict[str, Any],
    raw_text: str,
    *,
    structured_intent: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply a user correction through the atomic interrupt protocol.

    Does not skip running/verifying/repairing. Completed work from the rejected
    interpretation is marked tainted (not auto-preserved as sacred). SI compiles
    the correction into a canonical intent-operation state transition; callers
    do not supply replacement authority.
    """
    result = CP.compile_correction_transition(
        session,
        raw_text,
        structured_intent=structured_intent,
    )
    # Preserve legacy keys while exposing interrupt semantics.
    return {
        "intentEvent": result["intentEvent"],
        "operation": result["operation"],
        "invalidatedTaskIds": result["cancelledTaskIds"],
        "cancelledTaskIds": result["cancelledTaskIds"],
        "cancelRequestedTaskIds": result["cancelRequestedTaskIds"],
        "taintedEffectIds": result["taintedEffectIds"],
        "preservedCompletedTaskIds": [],  # completed work is tainted, not sacred
        "removed": result["removed"],
        "retained": result["retained"],
        "changed": result["changed"],
        "newCheckpoint": result["newCheckpoint"],
        "resumeRequiresApproval": True,
        "mutationFrozen": True,
    }


def record_policy_decision(session: dict[str, Any], decision: dict[str, Any]) -> None:
    session["policyDecisions"].append(decision)
    record_event(
        session,
        "policy.decision",
        {"decisionId": decision["decisionId"], "decision": decision["decision"], "taskId": decision["taskId"]},
    )


def record_artifact(session: dict[str, Any], artifact: dict[str, Any]) -> None:
    session["artifacts"].append(artifact)
    record_event(session, "artifact.recorded", {"artifactId": artifact.get("artifactId"), "taskId": artifact.get("taskId")})


def record_command(session: dict[str, Any], evidence: dict[str, Any]) -> None:
    session["commandEvidence"].append(evidence)
    record_event(
        session,
        "command.completed",
        {"evidenceId": evidence["evidenceId"], "taskId": evidence["taskId"], "exitCode": evidence["exitCode"]},
    )


def record_verification(session: dict[str, Any], task_id: str, evidence_id: str, passed: bool) -> dict[str, Any]:
    attempt = {
        "verificationId": _id("verify"),
        "taskId": task_id,
        "commandEvidenceId": evidence_id,
        "passed": passed,
        "timestamp": _now(),
    }
    session["verificationAttempts"].append(attempt)
    record_event(session, "verification.completed", attempt)
    return attempt


# Compatibility lane graph API -------------------------------------------------

def make_instance(lane_def: dict[str, Any]) -> dict[str, Any]:
    iso = lane_def.get("isolationPolicy", {})
    return {
        "laneInstanceId": _id("lane"),
        "laneDefinitionId": lane_def["id"],
        "laneVersion": lane_def["version"],
        "dependencyLaneIds": [],
        "status": "pending",
        "selectedContext": [],
        "assumptions": [],
        "assignedAgents": [],
        "branch": None,
        "worktreePath": None,
        "writableScopes": list(iso.get("writableScopes", [])),
        "requiresWorktree": bool(iso.get("requiresWorktree", False)),
        "inputs": [],
        "outputs": [],
        "attempts": [],
        "verificationResults": [],
        "humanActions": [],
        "createdAt": _now(),
        "updatedAt": _now(),
        "completedAt": None,
    }


def compile_project(objective: str, lane_ids: list[str]) -> tuple[dict[str, Any] | None, list[str]]:
    if reg is None:
        return None, ["lane_registry unavailable"]
    lanes, errors = reg.load_lanes()
    if errors:
        return None, errors
    missing = [lane_id for lane_id in lane_ids if lane_id not in lanes]
    if missing:
        return None, [f"unknown lane(s): {', '.join(missing)}"]
    session = new_session(objective)
    definition_to_instance: dict[str, str] = {}
    for lane_id in lane_ids:
        instance = make_instance(lanes[lane_id])
        session["lanes"][instance["laneInstanceId"]] = instance
        definition_to_instance[lane_id] = instance["laneInstanceId"]
    for instance in session["lanes"].values():
        manifest = lanes[instance["laneDefinitionId"]]
        instance["dependencyLaneIds"] = [
            definition_to_instance[dep]
            for dep in manifest.get("dependencies", [])
            if dep in definition_to_instance
        ]
    recompute_ready(session)
    return session, []


def recompute_ready(session: dict[str, Any]) -> None:
    lanes = session.get("lanes", {})
    for instance in lanes.values():
        if instance["status"] not in {"pending", "waiting_dependency"}:
            continue
        if all(lanes.get(dep, {}).get("status") == "complete" for dep in instance.get("dependencyLaneIds", [])):
            instance["status"] = "ready"
        else:
            instance["status"] = "waiting_dependency"


def transition(session: dict[str, Any], lane_instance_id: str, status: str) -> tuple[bool, str]:
    instance = session.get("lanes", {}).get(lane_instance_id)
    if not instance:
        return False, "lane instance not found"
    if status not in LANE_STATUSES:
        return False, f"invalid lane status: {status}"
    current = instance["status"]
    if status not in ALLOWED_LANE_TRANSITIONS.get(current, set()):
        return False, f"illegal transition {current} -> {status}"
    instance["status"] = status
    instance["updatedAt"] = _now()
    if status == "complete":
        instance["completedAt"] = _now()
    record_event(session, "lane.transition", {"laneInstanceId": lane_instance_id, "from": current, "to": status})
    recompute_ready(session)
    return True, "ok"


def set_lane_outputs(session: dict[str, Any], lane_instance_id: str, outputs: list[Any]) -> None:
    session["lanes"][lane_instance_id]["outputs"] = outputs
    session["lanes"][lane_instance_id]["updatedAt"] = _now()


def set_lane_human_actions(session: dict[str, Any], lane_instance_id: str, actions: list[Any]) -> None:
    session["lanes"][lane_instance_id]["humanActions"] = list(actions)
    session["lanes"][lane_instance_id]["updatedAt"] = _now()


def session_human_actions(session: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for lane in session.get("lanes", {}).values():
        for action in lane.get("humanActions", []):
            if isinstance(action, dict) and action.get("resolved"):
                continue
            result.append({"lane": lane["laneDefinitionId"], "laneInstanceId": lane["laneInstanceId"], "action": action})
    result.extend(a for a in session.get("humanActions", []) if not a.get("resolved"))
    return result


def global_state(session: dict[str, Any]) -> str:
    tasks = list(session.get("queue", {}).values())
    active = [task for task in tasks if task["status"] not in {"complete", "invalidated", "cancelled"}]
    if any(task["status"] in RUNNABLE_TASKS for task in active):
        return "RUNNING"
    if active and all(task["status"] == "human_blocked" for task in active):
        return "HUMAN_BLOCKED"
    if any(task["status"] == "failed" for task in active):
        return "FAILED"
    if not active and tasks:
        passed = any(v.get("passed") for v in session.get("verificationAttempts", []))
        return "VERIFIED_COMPLETE" if passed else "AWAITING_VERIFICATION"
    lanes = list(session.get("lanes", {}).values())
    if lanes:
        statuses = [lane["status"] for lane in lanes]
        if any(status in {"ready", "running", "verifying", "repairing"} for status in statuses):
            return "RUNNING"
        if all(status == "complete" for status in statuses):
            integration = [lane for lane in lanes if lane["laneDefinitionId"] == "si.integration" or lane["laneDefinitionId"].startswith("integration.")]
            return "COMPLETE" if integration and all(lane["status"] == "complete" for lane in integration) else "AWAITING_INTEGRATION"
        if any(status == "human_blocked" for status in statuses):
            return "HUMAN_BLOCKED"
        if any(status == "system_error" for status in statuses):
            return "SYSTEM_ERROR"
    return "EMPTY"


def summary(session: dict[str, Any]) -> dict[str, Any]:
    current = CP.current_checkpoint(session)
    authorized = CP.authorized_checkpoint(session)
    return {
        "sessionId": session["sessionId"],
        "state": global_state(session),
        "objective": session["objective"],
        "siActive": session.get("siActive", False),
        "governanceMode": session.get("governanceMode"),
        "activeIntent": session["activeIntent"],
        "queue": list(session["queue"].values()),
        "knownFacts": session["knownFacts"],
        "capabilityInventory": session["capabilityInventory"],
        "humanActions": session_human_actions(session),
        "executionLocked": session.get("executionLocked", True),
        "mutationFrozen": session.get("mutationFrozen", True),
        "correctionMode": session.get("correctionMode", False),
        "authorizedCheckpointId": session.get("authorizedCheckpointId"),
        "authorizedIntentHash": session.get("authorizedIntentHash"),
        "currentCheckpoint": CP.checkpoint_public_view(current) if current else None,
        "authorizedCheckpoint": CP.checkpoint_public_view(authorized) if authorized else None,
        "taintedEffectIds": list(session.get("taintedEffectIds") or []),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="SI authoritative lane/project session")
    sub = parser.add_subparsers(dest="command", required=True)
    show = sub.add_parser("show")
    show.add_argument("--session", required=True)
    ready = sub.add_parser("ready")
    ready.add_argument("--session", required=True)
    args = parser.parse_args()
    session = load_session(args.session)
    if not session:
        print(json.dumps({"error": "session not found"}))
        return 4
    if args.command == "ready":
        print(json.dumps({"sessionId": session["sessionId"], "ready": ready_tasks(session), "state": global_state(session)}, indent=2))
    else:
        print(json.dumps(summary(session), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
