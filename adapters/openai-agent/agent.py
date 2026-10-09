#!/usr/bin/env python3
"""Export/register an SI Managed Agent. Export is offline; no model runs here."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import urllib.error
import urllib.request
from typing import Any

import bootstrap

ROOT = Path(__file__).resolve().parent
API_ROOT = "https://api.openai.com/v1"
MODEL = "gpt-6-astra"

PREPARED_DEFINITION_SHA256 = "cfb5e0dff556d6fc99a2aa4ff5c7e800e80d22a1e2859478e274476ea9aba0a1"


def prepared_definition() -> dict[str, Any]:
    """Read the exact reviewed packet; packaging grants no extra capabilities."""
    source = ROOT / "prepared-definition.json"
    if source.is_symlink():
        raise ValueError("Prepared definition must not be a symlink")
    # Git may check out JSON with CRLF; instruction escapes remain unchanged.
    raw = source.read_bytes().replace(b"\r\n", b"\n")
    if hashlib.sha256(raw).hexdigest() != PREPARED_DEFINITION_SHA256:
        raise ValueError("Prepared definition differs from the reviewed packet")
    return json.loads(raw)


def encode(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def definition(model: str = MODEL) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", model):
        raise ValueError("Invalid explicit model identifier")
    payload = prepared_definition()
    if model != payload["model"]:
        raise ValueError("This preparation is reviewed only for gpt-6-astra")
    return payload


def environment(resources: Path | None = None) -> dict[str, Any]:
    source = ROOT / "bootstrap.py"
    if source.is_symlink():
        raise ValueError("Bootstrap must not be a symlink")
    result = {"type": "openai_hosted",
            "network": {"access": "restricted", "allowed_domains": ["github.com"]},
            "files": [{"type": "inline", "path": "/workspace/si-agent-bootstrap.py",
                       "data": base64.b64encode(source.read_bytes()).decode("ascii")}],
            "setup_commands": [{"command": "python3 /workspace/si-agent-bootstrap.py", "cwd": "/workspace"}],
            "capability_directories": ["/workspace/si-source/skills"]}
    if resources is not None:
        raw, _, _ = bootstrap.read_resources(resources)
        result["network"] = {"access": "disabled"}
        result["files"].append({"type": "inline", "path": "/workspace/si-source-e194.zip",
                                "data": base64.b64encode(raw).decode("ascii")})
        result["setup_commands"] = [{"command": "python3 /workspace/si-agent-bootstrap.py --install-resources /workspace/si-source-e194.zip --destination /workspace/si-source", "cwd": "/workspace"}]
    return result


def session_request(agent_id: str, prompt: str, lane: str) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", agent_id):
        raise ValueError("A provider-returned agent ID is required")
    if not prompt.strip() or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", lane):
        raise ValueError("A nonempty task and explicit project lane are required")
    bootstrap.require_hosted_source()
    return {"agent_id": agent_id, "environment": environment(), "input": prompt,
            "stream": False, "metadata": {"si_lane": lane, "si_source": bootstrap.SOURCE_COMMIT}}


def write_new(path: Path, value: Any) -> None:
    """Never silently replace an existing receipt or export."""
    if path.parent.resolve() != path.parent.absolute() or path.is_symlink():
        raise ValueError("Output must not redirect through a symlink")
    with path.open("xb") as handle:
        handle.write(encode(value))
        handle.flush()
        os.fsync(handle.fileno())


def export(destination: Path, model: str = MODEL, resources: Path | None = None) -> dict[str, Any]:
    payload = definition(model)
    destination = destination.absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError("Export destination must be new")
    if destination.parent.resolve() != destination.parent:
        raise ValueError("Export parent must be a real directory")
    env = environment(resources)
    destination.mkdir()
    write_new(destination / "agent.json", payload)
    write_new(destination / "session-environment.json", env)
    (destination / "instructions.md").write_text(payload["instructions"], encoding="utf-8", newline="\n")
    receipt = {"status": "configuration_exported_not_registered",
               "source_commit": bootstrap.SOURCE_COMMIT, "source_tree": bootstrap.SOURCE_TREE,
               "definition_sha256": hashlib.sha256(encode(payload)).hexdigest(),
               "bootstrap_sha256": hashlib.sha256((ROOT / "bootstrap.py").read_bytes()).hexdigest(),
               "environment_sha256": hashlib.sha256(encode(env)).hexdigest(),
               "source_delivery": "pinned_inline_canonical_resources" if resources else "local_only_not_publicly_fetchable",
               "resource_sha256": bootstrap.RESOURCE_SHA256 if resources else None,
               "registration_allowed": False, "session_preparation_allowed": False,
               "prepared_definition_sha256": PREPARED_DEFINITION_SHA256,
               "multi_agent_enabled": payload["multi_agent"]["enabled"],
               "plugin_modified": False, "api_calls": 0,
               "full_source_fetch_tested": False, "live_agent_run_tested": False}
    write_new(destination / "export-receipt.json", receipt)
    return receipt


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        raise RuntimeError("Refusing to redirect a credentialed OpenAI request")


def api_request(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Fixed official origin, TLS verification, no automatic write retries."""
    key = os.environ.get("OPENAI_API_KEY", "")
    project = os.environ.get("OPENAI_PROJECT_ID", "")
    if not key or not re.fullmatch(r"proj_[A-Za-z0-9_-]+", project):
        raise ValueError("An authorized OpenAI application key and explicit project ID must be configured outside chat")
    permitted = (method == "POST" and path == "/agents") or (
        method == "GET" and bool(re.fullmatch(r"/agents/[A-Za-z0-9_-]{1,64}", path))
        and path != "/agents/sessions")
    if not permitted:
        raise ValueError("This registration helper only accesses reusable-agent endpoints")
    bootstrap.require_hosted_source()
    request = urllib.request.Request(API_ROOT + path, data=encode(payload) if payload is not None else None,
        method=method, headers={"Authorization": "Bearer " + key, "OpenAI-Project": project,
                               "OpenAI-Beta": "agents=v1", "Content-Type": "application/json"})
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=60) as response:
            data = response.read(4_194_305)
        if len(data) > 4_194_304:
            raise RuntimeError("Unexpectedly large provider response")
        result = json.loads(data)
        if not isinstance(result, dict):
            raise RuntimeError("Provider response is not an object")
        return result
    except urllib.error.HTTPError as exc:
        # Do not print response bodies, headers, or credentials.
        raise RuntimeError(f"OpenAI returned HTTP {exc.code}; no retry was sent") from None
    except urllib.error.URLError:
        raise RuntimeError("OpenAI request failed; outcome may be uncertain; no retry was sent") from None


def register(state: Path, model: str = MODEL, request: Any = api_request) -> dict[str, Any]:
    """Register only. No session, inference, public sharing, or deletion."""
    payload = definition(model)
    project = os.environ.get("OPENAI_PROJECT_ID", "")
    if not os.environ.get("OPENAI_API_KEY") or not re.fullmatch(r"proj_[A-Za-z0-9_-]+", project):
        raise ValueError("No authorized OpenAI project credential is configured")
    bootstrap.require_hosted_source()
    operation = {"status": "registration_attempted_reconcile_before_retry", "project_id": project,
                 "definition_sha256": hashlib.sha256(encode(payload)).hexdigest(),
                 "source_commit": bootstrap.SOURCE_COMMIT}
    # An exclusive intent receipt prevents blind retries after a lost response.
    write_new(state, operation)
    created = request("POST", "/agents", payload)
    if not isinstance(created, dict):
        raise RuntimeError("Creation result is not an object; reconcile the project before retrying")
    agent_id = created.get("id")
    if not isinstance(agent_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", agent_id):
        raise RuntimeError("Creation result has no valid agent ID; reconcile the project before retrying")
    received = {**operation, "status": "created_readback_pending", "agent_id": agent_id}
    write_new(state.with_name(state.name + ".created.json"), received)
    observed = request("GET", "/agents/" + agent_id)
    if not isinstance(observed, dict) or observed.get("id") != agent_id:
        raise RuntimeError("Readback agent ID does not match the created agent; do not start a session")
    if any(observed.get(field) != payload[field] for field in ("name", "model", "instructions", "multi_agent")):
        raise RuntimeError("Saved agent differs from the requested definition; do not start a session")
    if observed.get("tools", []) != []:
        raise RuntimeError("Saved agent has tools absent from the reviewed definition")
    result = {**received, "status": "registered_readback_verified_not_live_tested", "sessions_started": 0}
    write_new(state.with_name(state.name + ".verified.json"), result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["export", "register"])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--source-resources", type=Path)
    parser.add_argument("--approve-registration", action="store_true")
    args = parser.parse_args()
    if args.action == "register" and not args.approve_registration:
        parser.error("register requires explicit --approve-registration; export is offline")
    if args.action == "register" and args.source_resources:
        parser.error("--source-resources is an offline export input, not registration authority")
    result = export(args.output, args.model, args.source_resources) if args.action == "export" else register(args.output, args.model)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
