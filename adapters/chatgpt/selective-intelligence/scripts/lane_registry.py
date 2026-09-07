#!/usr/bin/env python3
"""SI lane registry — the kernel's first primitive.

Loads durable lane manifests from ``lanes/*.json``, validates them structurally
(dependency-free, mirroring the other SI validators), and resolves their dependency
order. A lane is a durable product capability defined by a typed contract, not a prompt.
See ``schemas/lane.schema.json`` for the full contract.

Usage:
  python lane_registry.py validate   # exit 1 if any manifest is invalid
  python lane_registry.py list        # one line per lane
  python lane_registry.py resolve     # JSON topological order, or errors
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
LANES_DIR = SKILL_ROOT / "lanes"

ID_RE = re.compile(r"^[a-z][a-z0-9]*([.-][a-z0-9]+)*$")
SEMVER_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
FS = {"none", "read", "write-scoped", "write"}
GIT = {"none", "read", "worktree", "commit"}
NET = {"none", "restricted", "full"}
SEC = {"none", "reference-only", "read"}
ROLES = {"primary", "researcher", "specialist", "implementer", "reviewer", "verifier", "diagnostic", "integrator", "planner"}
REQUIRED = ("id", "version", "purpose", "owns", "inputs", "outputs", "permissions", "agentPolicy", "isolationPolicy", "completionGates", "humanBlockerPolicy")


def validate_lane(m: dict, errors: list[str]) -> None:
    lid = m.get("id", "<no-id>")

    def err(msg: str) -> None:
        errors.append(f"{lid}: {msg}")

    for key in REQUIRED:
        if key not in m:
            err(f"missing required field '{key}'")
    if not isinstance(m.get("id"), str) or not ID_RE.fullmatch(m.get("id", "")):
        err("invalid id (need lowercase dotted/dashed slug)")
    if not SEMVER_RE.fullmatch(str(m.get("version", ""))):
        err("invalid version (need x.y.z)")
    for arrk in ("owns", "inputs", "outputs", "completionGates"):
        if arrk in m and not isinstance(m[arrk], list):
            err(f"{arrk} must be an array")
    if isinstance(m.get("completionGates"), list) and not m["completionGates"]:
        err("completionGates must be non-empty (generated code existing is never a gate)")

    perm = m.get("permissions")
    if isinstance(perm, dict):
        if perm.get("filesystem") not in FS:
            err("permissions.filesystem invalid")
        if not isinstance(perm.get("shell"), bool):
            err("permissions.shell must be boolean")
        if perm.get("git") not in GIT:
            err("permissions.git invalid")
        if perm.get("network") not in NET:
            err("permissions.network invalid")
        if perm.get("secrets") not in SEC:
            err("permissions.secrets invalid")
    else:
        err("permissions must be an object")

    ap = m.get("agentPolicy")
    if isinstance(ap, dict):
        d, mx = ap.get("defaultAgents"), ap.get("maximumAgents")
        if not isinstance(d, int) or d < 0:
            err("agentPolicy.defaultAgents invalid")
        if not isinstance(mx, int) or mx < 0:
            err("agentPolicy.maximumAgents invalid")
        if isinstance(d, int) and isinstance(mx, int) and d > mx:
            err("agentPolicy.defaultAgents exceeds maximumAgents")
        roles = ap.get("roles", [])
        if not isinstance(roles, list) or any(r not in ROLES for r in roles):
            err("agentPolicy.roles has an unknown role")
    else:
        err("agentPolicy must be an object")

    iso = m.get("isolationPolicy")
    if isinstance(iso, dict):
        if not isinstance(iso.get("requiresWorktree"), bool):
            err("isolationPolicy.requiresWorktree must be boolean")
        if not isinstance(iso.get("writableScopes", []), list):
            err("isolationPolicy.writableScopes must be an array")
    else:
        err("isolationPolicy must be an object")

    hb = m.get("humanBlockerPolicy")
    if not isinstance(hb, dict) or not isinstance(hb.get("continueIndependentWork"), bool):
        err("humanBlockerPolicy.continueIndependentWork must be boolean")

    if "dependencies" in m and not isinstance(m["dependencies"], list):
        err("dependencies must be an array")


def load_lanes() -> tuple[dict, list[str]]:
    lanes: dict = {}
    errors: list[str] = []
    if not LANES_DIR.exists():
        return lanes, ["lanes/ directory not found"]
    for p in sorted(LANES_DIR.glob("*.json")):
        try:
            m = json.loads(p.read_text(encoding="utf-8"))
        except (ValueError, json.JSONDecodeError) as e:
            errors.append(f"{p.name}: invalid JSON ({e})")
            continue
        validate_lane(m, errors)
        lid = m.get("id")
        if lid in lanes:
            errors.append(f"{lid}: duplicate lane id")
        if lid:
            lanes[lid] = m
    return lanes, errors


def resolve_order(lanes: dict, errors: list[str]) -> list[str]:
    deps = {lid: list(lanes[lid].get("dependencies", [])) for lid in lanes}
    for lid, ds in deps.items():
        for d in ds:
            if d not in lanes:
                errors.append(f"{lid}: dependency '{d}' not in registry")
    order: list[str] = []
    seen: set = set()
    changed = True
    while changed:
        changed = False
        for lid in lanes:
            if lid in seen:
                continue
            if all((d in order) or (d not in lanes) for d in deps[lid]):
                order.append(lid)
                seen.add(lid)
                changed = True
    if len(order) < len(lanes):
        errors.append("dependency cycle among: " + ", ".join(sorted(set(lanes) - set(order))))
    return order


def cmd_validate(_args: argparse.Namespace) -> int:
    lanes, errors = load_lanes()
    if errors:
        for e in errors:
            print(f"FAIL {e}", file=sys.stderr)
        return 1
    print(f"OK: {len(lanes)} lane(s) valid")
    return 0


def cmd_list(_args: argparse.Namespace) -> int:
    lanes, errors = load_lanes()
    for lid in sorted(lanes):
        m = lanes[lid]
        print(
            f"{lid}@{m.get('version')}  deps={m.get('dependencies', [])}  "
            f"agents<={m.get('agentPolicy', {}).get('maximumAgents')}  "
            f"worktree={m.get('isolationPolicy', {}).get('requiresWorktree')}"
        )
    if errors:
        print(f"({len(errors)} validation issue(s); run validate)", file=sys.stderr)
        return 1
    return 0


def cmd_resolve(_args: argparse.Namespace) -> int:
    lanes, errors = load_lanes()
    order = resolve_order(lanes, errors)
    if errors:
        for e in errors:
            print(f"FAIL {e}", file=sys.stderr)
        return 1
    print(json.dumps({"order": order}))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="SI lane registry")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("validate", help="validate all lane manifests").set_defaults(func=cmd_validate)
    sub.add_parser("list", help="list lanes").set_defaults(func=cmd_list)
    sub.add_parser("resolve", help="print dependency order").set_defaults(func=cmd_resolve)
    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
