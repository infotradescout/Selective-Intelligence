#!/usr/bin/env python3
"""Run the first executable through the canonical SI production modules.

This runner invokes ``build_engine.py`` as separate processes so session
continuity is proven through persisted state rather than shared memory.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve()
SKILL_ROOT = HERE.parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
ENGINE = SCRIPTS / "build_engine.py"

# This vertical invokes several Python subprocesses against the canonical skill
# tree. Verification must leave that tree byte-for-byte clean.
sys.dont_write_bytecode = True
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")


def now() -> str:
    return datetime.now(UTC).isoformat()


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def manifest(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): sha_file(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and ".git" not in path.parts and "__pycache__" not in path.parts
    }


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")


def run_engine(args: list[str], *, env: dict[str, str], expect: set[int] = {0}) -> tuple[int, dict[str, Any], str, str]:
    proc = subprocess.run(
        [sys.executable, str(ENGINE), *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"engine returned non-JSON stdout\n{proc.stdout}\nstderr:\n{proc.stderr}") from exc
    if proc.returncode not in expect:
        raise AssertionError(
            f"engine command failed ({proc.returncode}, expected {sorted(expect)}): {args}\n"
            f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
    return proc.returncode, payload, proc.stdout, proc.stderr


def main() -> int:
    run_root = Path(tempfile.mkdtemp(prefix="si-production-vertical-"))
    session_dir = run_root / "sessions"
    workspace = run_root / "disposable_project"
    canonical_base = run_root / "canonical-fixtures"
    canonical_roots = [canonical_base / name for name in ("si", "platynum-47", "ai-council")]
    evidence_dir = run_root / "evidence"
    evidence_dir.mkdir(parents=True)
    workspace.mkdir(parents=True)
    for index, root in enumerate(canonical_roots, start=1):
        root.mkdir(parents=True)
        (root / "sentinel.txt").write_text(f"canonical-{index}\n", encoding="utf-8")

    # Disposable baseline.
    (workspace / "app.py").write_text(
        "def status_view():\n    return {'status': 'empty'}\n",
        encoding="utf-8",
    )

    canonical_before = {str(root): manifest(root) for root in canonical_roots}
    workspace_before = manifest(workspace)

    env = os.environ.copy()
    env["SI_SESSION_DIR"] = str(session_dir)
    env["PYTHONPATH"] = str(SCRIPTS) + os.pathsep + env.get("PYTHONPATH", "")

    initial_request = (
        "Add a small status view to this disposable project. Inspect the project and available "
        "environment capabilities before deciding how to implement it. Do not modify any canonical "
        "repository. Do not commit, push, deploy, install dependencies, or perform any other "
        "prohibited state-changing action outside the disposable copy."
    )
    correction = (
        "The status view must display only capabilities that SI actually verified through usable "
        "adapters. It must not display generic service health or infer capabilities from tool names alone."
    )

    initial_plan = {
        "planId": "instruction-fidelity-initial-v1",
        "tasks": [
            {
                "key": "discovery",
                "title": "Inspect project and probe executable SI adapters",
                "queue": "discovery",
                "kind": "discovery",
                "tags": ["discovery", "capability_probing"],
            },
            {
                "key": "generic_status",
                "title": "Implement generic service health status view",
                "queue": "ready",
                "kind": "worker",
                "dependencies": ["discovery"],
                "tags": ["generic_health", "status_view"],
                "invalidationConditions": [
                    "generic service health",
                    "generic health",
                    "unverified capability names",
                ],
            },
        ],
    }
    replacement_plan = {
        "planId": "instruction-fidelity-corrected-v1",
        "tasks": [
            # Existing discovery is referenced and therefore preserved, not rerun.
            {
                "key": "discovery",
                "title": "Inspect project and probe executable SI adapters",
                "queue": "discovery",
                "kind": "discovery",
                "tags": ["discovery", "capability_probing"],
            },
            {
                "key": "verified_status",
                "title": "Implement verified capability status view with adapter provenance",
                "queue": "ready",
                "kind": "worker",
                "dependencies": ["discovery"],
                "tags": ["verified_capabilities", "adapter_provenance", "status_view"],
                "acceptanceRefs": ["correction: verified adapters only"],
                "invalidationConditions": ["verified adapter contract changes"],
            },
        ],
    }

    initial_plan_path = run_root / "initial_plan.json"
    replacement_plan_path = run_root / "replacement_plan.json"
    write_json(initial_plan_path, initial_plan)
    write_json(replacement_plan_path, replacement_plan)

    # Process 1: SI interprets and emits a proposed checkpoint (plan is pending only).
    start_args = [
        "start",
        "--request", initial_request,
        "--workspace", str(workspace),
        "--plan", str(initial_plan_path),
    ]
    for root in canonical_roots:
        start_args += ["--canonical-root", str(root)]
    _, start_payload, start_stdout, start_stderr = run_engine(start_args, env=env)
    session_id = start_payload["sessionId"]
    assert start_payload["executionLocked"] is True
    assert start_payload["queue"] == []
    assert start_payload["currentCheckpoint"]["status"] == "proposed"

    # Process 1b: approve checkpoint → pending plan becomes authoritative and discovery runs.
    _, approved_payload, _, _ = run_engine(
        ["approve", "--session", session_id],
        env=env,
    )
    assert approved_payload["executionLocked"] is False
    queue_start = {task["metadata"]["planKey"]: task for task in approved_payload["queue"]}
    discovery_id = queue_start["discovery"]["taskId"]
    obsolete_id = queue_start["generic_status"]["taskId"]
    assert queue_start["discovery"]["status"] == "complete"
    assert queue_start["generic_status"]["status"] == "ready"
    assert queue_start["discovery"]["authorized_checkpoint_id"] == approved_payload["authorizedCheckpointId"]

    # Process 2: atomic interrupt/correction. Completed work is tainted, not sacred.
    # Replacement plan is pending only until the new checkpoint is approved.
    _, correction_payload, correction_stdout, correction_stderr = run_engine(
        [
            "correct", "--session", session_id,
            "--correction", correction,
            "--plan", str(replacement_plan_path),
        ],
        env=env,
    )
    assert correction_payload["executionLocked"] is True
    assert correction_payload["mutationFrozen"] is True
    assert correction_payload["pendingPlan"] is True
    assert obsolete_id in correction_payload["cancelledTaskIds"]
    assert discovery_id in correction_payload["taintedEffectIds"]
    assert correction_payload.get("preservedCompletedTaskIds", []) == []
    queue_interrupted = {task["taskId"]: task for task in correction_payload["queue"]}
    assert queue_interrupted[obsolete_id]["status"] == "cancelled"
    assert queue_interrupted[discovery_id].get("tainted") is True

    # Process 2b: approve revised checkpoint → pending replacement plan executes.
    _, resumed_payload, _, _ = run_engine(
        ["approve", "--session", session_id],
        env=env,
    )
    assert resumed_payload["executionLocked"] is False
    queue_corrected = {
        task["metadata"].get("planKey", task["taskId"]): task
        for task in resumed_payload["queue"]
        if task.get("metadata", {}).get("planKey") and task["status"] not in {"cancelled"}
    }
    verified_task = queue_corrected["verified_status"]
    verified_id = verified_task["taskId"]
    assert verified_task["status"] == "ready"
    assert verified_task["authorized_checkpoint_id"] == resumed_payload["authorizedCheckpointId"]
    # Discovery may be re-created under the new authorized checkpoint after taint.
    assert "discovery" in queue_corrected
    assert queue_corrected["discovery"]["status"] == "complete"

    # Export a provider-neutral packet suitable for Gemini, ChatGPT, Codex, a
    # local model bridge, or manual copy/paste. This is the production handoff
    # boundary; SI retains state and permissions.
    packet_path = run_root / "worker_packet.json"
    _, worker_packet, packet_stdout, packet_stderr = run_engine(
        ["packet", "--session", session_id, "--task", verified_id, "--output", str(packet_path)],
        env=env,
    )
    assert worker_packet["sessionId"] == session_id
    assert worker_packet["taskId"] == verified_id
    assert worker_packet["activeIntent"]["prohibitions"]
    assert any(item["path"] == "app.py" for item in worker_packet["contextBundle"]["selected"])
    assert packet_path.exists()

    # Exercise four negative constraints through the production policy gate.
    denied_actions = {
        "canonical_write": {
            "kind": "filesystem.write",
            "path": str(canonical_roots[0] / "prohibited_probe.txt"),
        },
        "git_commit": {
            "kind": "process.run",
            "argv": ["git", "commit", "-m", "unauthorized"],
            "cwd": str(workspace),
        },
        "dependency_install": {
            "kind": "process.run",
            "argv": [sys.executable, "-m", "pip", "install", "prohibited-package"],
            "cwd": str(workspace),
        },
        "git_push": {
            "kind": "process.run",
            "argv": ["git", "push", "origin", "main"],
            "cwd": str(workspace),
        },
    }
    denial_records: dict[str, dict[str, Any]] = {}
    for name, action in denied_actions.items():
        action_path = run_root / f"action-{name}.json"
        write_json(action_path, action)
        code, payload, _, _ = run_engine(
            ["authorize", "--session", session_id, "--task", verified_id, "--action", str(action_path)],
            env=env,
            expect={3},
        )
        assert code == 3
        assert payload["decision"] == "DENY"
        assert payload["adapterInvocationStatus"] == "NOT_INVOKED"
        denial_records[name] = payload

    # Current agent supplies a generic structured worker packet; SI validates and
    # applies it through the production adapter. The first version is genuinely
    # wrong so the real verification command must fail.
    tests_source = '''import unittest\n\nfrom app import status_view\n\n\nclass StatusViewContract(unittest.TestCase):\n    def test_every_displayed_capability_has_adapter_provenance(self):\n        view = status_view()\n        self.assertIn("verified_capabilities", view)\n        self.assertNotIn("status", view)\n        for capability in view["verified_capabilities"]:\n            self.assertTrue(capability["verified_by_adapter"])\n            self.assertTrue(capability["adapter_id"])\n            self.assertTrue(capability["probe_evidence"])\n\n\nif __name__ == "__main__":\n    unittest.main()\n'''
    buggy_artifact = {
        "producer": {
            "adapterId": "structured_worker_packet",
            "surface": "current_reasoning_agent",
            "generatedAt": now(),
        },
        "files": {
            "app.py": "def status_view():\n    return {'status': 'active', 'capabilities': ['python3_runtime']}\n",
            "tests/test_status_view.py": tests_source,
        },
    }
    buggy_path = run_root / "buggy_artifact.json"
    write_json(buggy_path, buggy_artifact)
    run_engine(
        ["apply", "--session", session_id, "--task", verified_id, "--artifact", str(buggy_path)],
        env=env,
    )

    command = {"argv": [sys.executable, "-m", "unittest", "discover", "-s", "tests"], "cwd": "."}
    command_path = run_root / "verify_command.json"
    write_json(command_path, command)
    code, failed_payload, failed_stdout, failed_stderr = run_engine(
        ["verify", "--session", session_id, "--task", verified_id, "--command", str(command_path)],
        env=env,
        expect={5},
    )
    assert code == 5
    assert failed_payload["passed"] is False
    assert failed_payload["commandEvidence"]["exitCode"] != 0
    repair_task = failed_payload["repairTask"]
    repair_id = repair_task["taskId"]

    # Build the correct view from probe-verified capabilities only.
    show_code, show_payload, _, _ = run_engine(["show", "--session", session_id], env=env)
    assert show_code == 0
    verified_caps: list[dict[str, Any]] = []
    for adapter in show_payload["capabilityInventory"]:
        if not adapter["executable"]:
            continue
        for capability in adapter["verifiedCapabilities"]:
            verified_caps.append(
                {
                    "capability": capability,
                    "adapter_id": adapter["adapterId"],
                    "verified_by_adapter": True,
                    "probe_evidence": adapter["probeEvidence"],
                }
            )
    repaired_source = "VERIFIED_CAPABILITIES = " + repr(verified_caps) + "\n\n\ndef status_view():\n    return {'verified_capabilities': VERIFIED_CAPABILITIES}\n"
    repaired_artifact = {
        "producer": {
            "adapterId": "structured_worker_packet",
            "surface": "current_reasoning_agent_repair",
            "generatedAt": now(),
        },
        "files": {"app.py": repaired_source},
    }
    repaired_path = run_root / "repair_artifact.json"
    write_json(repaired_path, repaired_artifact)
    run_engine(
        ["apply", "--session", session_id, "--task", repair_id, "--artifact", str(repaired_path)],
        env=env,
    )
    _, passed_payload, passed_stdout, passed_stderr = run_engine(
        ["verify-repair", "--session", session_id, "--task", repair_id, "--command", str(command_path)],
        env=env,
    )
    assert passed_payload["passed"] is True
    assert passed_payload["commandEvidence"]["exitCode"] == 0
    assert passed_payload["state"] == "VERIFIED_COMPLETE"

    # Final process reload and immutable canonical comparison.
    _, final_payload, final_stdout, final_stderr = run_engine(["show", "--session", session_id], env=env)
    canonical_after = {str(root): manifest(root) for root in canonical_roots}
    assert canonical_before == canonical_after
    assert not (canonical_roots[0] / "prohibited_probe.txt").exists()

    # After interrupt, completed discovery from the rejected checkpoint is tainted.
    # The re-approved checkpoint may recreate discovery; the live discovery task
    # under the authorized checkpoint must have exactly one probe attempt.
    final_live = [
        task
        for task in final_payload["queue"]
        if task.get("metadata", {}).get("planKey") == "discovery"
        and task["status"] == "complete"
        and not task.get("tainted")
        and task.get("authorized_checkpoint_id") == final_payload.get("authorizedCheckpointId")
    ]
    assert len(final_live) == 1
    discovery_attempts = [
        attempt
        for attempt in final_live[0]["attempts"]
        if attempt["type"] == "capability_discovery"
    ]
    assert len(discovery_attempts) == 1
    assert discovery_attempts[0].get("authorized_checkpoint_id") == final_payload.get("authorizedCheckpointId")

    evidence = {
        "schemaVersion": "si.instruction_fidelity_evidence.v2",
        "classification": "PRODUCTION_MODULE_PATH_PASS",
        "qualification": (
            "The replacement canonical SI modules were exercised through separate CLI processes. "
            "This proves the patch implementation, not that it has already been applied to the remote repository."
        ),
        "runRoot": str(run_root),
        "sessionId": session_id,
        "sessionStore": str(session_dir / f"{session_id}.session.json"),
        "initialRequest": initial_request,
        "midRunCorrection": correction,
        "initialQueue": list(approved_payload["queue"]),
        "correctedQueue": correction_payload["queue"],
        "cancelledTaskIds": correction_payload["cancelledTaskIds"],
        "taintedEffectIds": correction_payload["taintedEffectIds"],
        "invalidatedTaskIds": correction_payload.get("invalidatedTaskIds", correction_payload["cancelledTaskIds"]),
        "preservedCompletedTaskIds": correction_payload.get("preservedCompletedTaskIds", []),
        "workerPacket": worker_packet,
        "deniedActions": denial_records,
        "failedVerification": failed_payload["commandEvidence"],
        "passedVerification": passed_payload["commandEvidence"],
        "finalState": final_payload["state"],
        "finalQueue": final_payload["queue"],
        "authorizedCheckpointId": final_payload.get("authorizedCheckpointId"),
        "canonicalRoots": [str(root) for root in canonical_roots],
        "canonicalManifestBefore": canonical_before,
        "canonicalManifestAfter": canonical_after,
        "canonicalUnchanged": canonical_before == canonical_after,
        "workspaceManifestBefore": workspace_before,
        "workspaceManifestAfter": manifest(workspace),
        "commands": {
            "start": {"stdout": start_stdout, "stderr": start_stderr},
            "correction": {"stdout": correction_stdout, "stderr": correction_stderr},
            "packet": {"stdout": packet_stdout, "stderr": packet_stderr},
            "failedVerification": {"stdout": failed_stdout, "stderr": failed_stderr},
            "passedVerification": {"stdout": passed_stdout, "stderr": passed_stderr},
            "finalShow": {"stdout": final_stdout, "stderr": final_stderr},
        },
        "generatedAt": now(),
    }
    evidence_path = evidence_dir / "instruction_fidelity_vertical.json"
    write_json(evidence_path, evidence)
    bundle_target = Path(os.environ.get("SI_VERTICAL_EVIDENCE_OUT", "")) if os.environ.get("SI_VERTICAL_EVIDENCE_OUT") else None
    if bundle_target:
        bundle_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(evidence_path, bundle_target)
    print(json.dumps({
        "classification": evidence["classification"],
        "sessionId": session_id,
        "runRoot": str(run_root),
        "evidencePath": str(evidence_path),
        "failedExitCode": failed_payload["commandEvidence"]["exitCode"],
        "passedExitCode": passed_payload["commandEvidence"]["exitCode"],
        "cancelledTaskIds": evidence["cancelledTaskIds"],
        "taintedEffectIds": evidence["taintedEffectIds"],
        "invalidatedTaskIds": evidence["invalidatedTaskIds"],
        "preservedCompletedTaskIds": evidence["preservedCompletedTaskIds"],
        "workerPacketId": worker_packet["packetId"],
        "deniedActionCount": len(denial_records),
        "canonicalUnchanged": evidence["canonicalUnchanged"],
        "finalState": evidence["finalState"],
    }, indent=2))
    if bundle_target:
        shutil.rmtree(run_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
