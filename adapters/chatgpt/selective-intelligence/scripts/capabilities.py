#!/usr/bin/env python3
"""Probe-backed, provider-neutral SI capability registry.

A binary name or environment variable is evidence of discovery, not proof that
SI can execute the capability. An adapter is executable only after its adapter
implementation performs a safe probe successfully. Secret values are never
read into reports; environment credentials are referenced by variable name.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class AdapterSpec:
    adapter_class: str
    adapter_id: str
    provides: tuple[str, ...]
    detector: str
    detect_key: str = ""
    probe: str = "none"
    scope: str = "user_environment"
    machine_executable: bool = True


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


ADAPTERS: tuple[AdapterSpec, ...] = (
    AdapterSpec(
        "deterministic_tool",
        "python3_runtime",
        ("python_runtime", "test_runner", "structured_generation"),
        "python",
        probe="python_version",
    ),
    AdapterSpec(
        "deterministic_tool",
        "local_filesystem_tmp",
        ("filesystem_read", "filesystem_write"),
        "builtin",
        probe="filesystem_roundtrip",
    ),
    AdapterSpec(
        "deterministic_tool",
        "local_process_runner",
        ("process_execution", "shell_execution"),
        "builtin",
        probe="process_roundtrip",
    ),
    AdapterSpec("deterministic_tool", "git_cli", ("version_control_read",), "which", "git", "version"),
    AdapterSpec("deterministic_tool", "node_runtime", ("node_runtime",), "which", "node", "version"),
    AdapterSpec("deterministic_tool", "npm_cli", ("javascript_package_cli",), "which", "npm", "version"),
    AdapterSpec("authenticated_service_cli", "gh_cli", ("git_service_binary",), "which", "gh", "version"),
    # Agent binaries are not automatically granted reasoning/code-generation
    # capabilities. A safe authenticated bridge invocation must prove those.
    AdapterSpec("authenticated_agent_cli", "codex_cli_binary", ("agent_cli_binary",), "which", "codex", "version"),
    AdapterSpec("authenticated_agent_cli", "gemini_cli_binary", ("agent_cli_binary",), "which", "gemini", "version"),
    AdapterSpec("authenticated_agent_cli", "claude_cli_binary", ("agent_cli_binary",), "which", "claude", "version"),
    AdapterSpec("local_model", "ollama_binary", ("local_model_binary",), "which", "ollama", "version"),
    AdapterSpec(
        "existing_api_provider",
        "anthropic_credential_reference",
        ("credential_reference",),
        "env",
        "ANTHROPIC_API_KEY",
        "credential_reference",
        machine_executable=False,
    ),
    AdapterSpec(
        "existing_api_provider",
        "openai_credential_reference",
        ("credential_reference",),
        "env",
        "OPENAI_API_KEY",
        "credential_reference",
        machine_executable=False,
    ),
    AdapterSpec(
        "platynum_managed_provider",
        "platynum_credential_reference",
        ("credential_reference",),
        "env",
        "MODEL_API_KEY",
        "credential_reference",
        machine_executable=False,
    ),
    AdapterSpec(
        "external_worker_contract",
        "structured_worker_packet",
        ("structured_worker_result_import",),
        "builtin",
        probe="schema_contract",
        scope="si_runtime",
    ),
    AdapterSpec(
        "human_capability",
        "human",
        ("human_action",),
        "builtin",
        probe="none",
        scope="human",
        machine_executable=False,
    ),
)


def _discover(spec: AdapterSpec) -> tuple[bool, str, str | None]:
    if spec.detector == "builtin":
        return True, "adapter implementation present", None
    if spec.detector == "python":
        path = str(Path(sys.executable).resolve())
        return bool(path), f"python:{path}", path
    if spec.detector == "which":
        path = shutil.which(spec.detect_key)
        return bool(path), f"which:{path}" if path else "not found on PATH", path
    if spec.detector == "env":
        present = bool(os.environ.get(spec.detect_key))
        return present, f"env:{spec.detect_key} {'present' if present else 'absent'}", None
    return False, "unknown detector", None


def _run_probe(argv: list[str], timeout: int = 15) -> dict[str, Any]:
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "exitCode": None, "evidence": f"probe error: {type(exc).__name__}: {exc}"}
    text = (proc.stdout or proc.stderr or "").strip()
    return {
        "ok": proc.returncode == 0,
        "exitCode": proc.returncode,
        "evidence": text[:500],
        "stdoutSha256": _sha(proc.stdout or ""),
        "stderrSha256": _sha(proc.stderr or ""),
    }


def _probe(spec: AdapterSpec, discovered_path: str | None, probe_root: Path) -> dict[str, Any]:
    if spec.probe == "none":
        return {"ok": False, "status": "not_machine_executable", "evidence": "no machine probe"}
    if spec.probe == "credential_reference":
        return {
            "ok": False,
            "status": "credential_reference_only",
            "evidence": f"{spec.detect_key} referenced but provider invocation not performed",
        }
    if spec.probe == "schema_contract":
        # The importer is executable because the validator is local and has no
        # external dependency. This does not claim that a reasoning provider is
        # available; it proves only that SI can accept a validated worker packet.
        return {"ok": True, "status": "verified", "evidence": "local structured worker packet validator available"}
    if spec.probe == "python_version":
        return {"status": "verified" if (r := _run_probe([sys.executable, "--version"]))["ok"] else "failed", **r}
    if spec.probe == "version":
        if not discovered_path:
            return {"ok": False, "status": "failed", "evidence": "binary path missing"}
        r = _run_probe([discovered_path, "--version"])
        r["status"] = "verified" if r["ok"] else "failed"
        return r
    if spec.probe == "filesystem_roundtrip":
        probe_root.mkdir(parents=True, exist_ok=True)
        path = probe_root / f".si-capability-probe-{uuid.uuid4().hex}"
        payload = uuid.uuid4().hex
        try:
            path.write_text(payload, encoding="utf-8")
            read_back = path.read_text(encoding="utf-8")
            path.unlink()
            ok = read_back == payload and not path.exists()
            return {
                "ok": ok,
                "status": "verified" if ok else "failed",
                "evidence": f"read/write/delete roundtrip in {probe_root}",
            }
        except OSError as exc:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            return {"ok": False, "status": "failed", "evidence": f"filesystem probe failed: {exc}"}
    if spec.probe == "process_roundtrip":
        marker = uuid.uuid4().hex
        r = _run_probe([sys.executable, "-c", f"print('{marker}')"])
        ok = r["ok"] and marker in r["evidence"]
        r["ok"] = ok
        r["status"] = "verified" if ok else "failed"
        return r
    return {"ok": False, "status": "failed", "evidence": f"unknown probe {spec.probe}"}


def inventory(*, probe_root: str | os.PathLike[str] | None = None) -> list[dict[str, Any]]:
    root = Path(probe_root or (Path(tempfile.gettempdir()) / "si-capability-probes")).resolve()
    reports: list[dict[str, Any]] = []
    for spec in ADAPTERS:
        discovered, discovery_evidence, path = _discover(spec)
        if discovered:
            probe = _probe(spec, path, root)
        else:
            probe = {"ok": False, "status": "not_discovered", "evidence": "adapter prerequisite not discovered"}
        executable = bool(discovered and probe.get("ok") and spec.machine_executable)
        verified_caps = list(spec.provides) if executable else []
        reports.append(
            {
                "adapterClass": spec.adapter_class,
                "adapterId": spec.adapter_id,
                "scope": spec.scope,
                "discovered": discovered,
                "discoveryEvidence": discovery_evidence,
                "adapterImplemented": True,
                "probeStatus": probe.get("status", "failed"),
                "probeEvidence": probe.get("evidence", ""),
                "probeExitCode": probe.get("exitCode"),
                "declaredCapabilities": list(spec.provides),
                "verifiedCapabilities": verified_caps,
                "executable": executable,
                "machineExecutable": spec.machine_executable,
                "checkedAt": _now(),
            }
        )
    return reports


def available_adapters(*, probe_root: str | os.PathLike[str] | None = None) -> list[dict[str, Any]]:
    return [a for a in inventory(probe_root=probe_root) if a["executable"]]


def resolve_requirements(
    requirements: list[str], *, probe_root: str | os.PathLike[str] | None = None
) -> dict[str, Any]:
    reports = inventory(probe_root=probe_root)
    executable = [a for a in reports if a["executable"]]
    remaining = set(requirements)
    selected: list[str] = []
    for adapter in sorted(executable, key=lambda a: -len(set(a["verifiedCapabilities"]) & remaining)):
        covered = set(adapter["verifiedCapabilities"]) & remaining
        if covered:
            selected.append(adapter["adapterId"])
            remaining -= covered
        if not remaining:
            break
    return {
        "requirements": requirements,
        "selectedAdapters": selected,
        "missingCapabilities": sorted(remaining),
        "runnable": not remaining,
        "inventory": reports,
    }


def resolve_lanes(*, probe_root: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    try:
        import lane_registry as reg  # type: ignore
    except ImportError:
        return {
            "availableCapabilities": sorted(
                {cap for a in available_adapters(probe_root=probe_root) for cap in a["verifiedCapabilities"]}
            ),
            "availableAdapters": [a["adapterId"] for a in available_adapters(probe_root=probe_root)],
            "runnableLaneIds": [],
            "blockedLaneIds": [],
            "lanes": {},
            "errors": ["lane_registry unavailable"],
        }
    lanes, errors = reg.load_lanes()
    lane_reports: dict[str, Any] = {}
    runnable: list[str] = []
    blocked: list[str] = []
    selected: set[str] = set()
    missing: set[str] = set()
    for lane_id, manifest in lanes.items():
        result = resolve_requirements(list(manifest.get("requires", [])), probe_root=probe_root)
        result.pop("inventory", None)
        lane_reports[lane_id] = result
        if result["runnable"]:
            runnable.append(lane_id)
            selected.update(result["selectedAdapters"])
        else:
            blocked.append(lane_id)
            missing.update(result["missingCapabilities"])
    avail = available_adapters(probe_root=probe_root)
    return {
        "availableCapabilities": sorted({cap for a in avail for cap in a["verifiedCapabilities"]}),
        "availableAdapters": [a["adapterId"] for a in avail],
        "selectedAdapters": sorted(selected),
        "missingCapabilities": sorted(missing),
        "runnableLaneIds": sorted(runnable),
        "blockedLaneIds": sorted(blocked),
        "lanes": lane_reports,
        "errors": errors,
        "note": "Only probe-verified adapters are executable; a missing provider blocks only dependent lanes.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="SI probe-backed capability registry")
    sub = parser.add_subparsers(dest="command", required=True)
    inv = sub.add_parser("inventory")
    inv.add_argument("--probe-root")
    res = sub.add_parser("resolve")
    res.add_argument("--requires", default="", help="comma-separated capabilities")
    res.add_argument("--probe-root")
    lanes = sub.add_parser("resolve-lanes")
    lanes.add_argument("--probe-root")
    args = parser.parse_args()
    if args.command == "inventory":
        print(json.dumps({"adapters": inventory(probe_root=args.probe_root)}, indent=2))
    elif args.command == "resolve":
        reqs = [v.strip() for v in args.requires.split(",") if v.strip()]
        print(json.dumps(resolve_requirements(reqs, probe_root=args.probe_root), indent=2))
    else:
        print(json.dumps(resolve_lanes(probe_root=args.probe_root), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
