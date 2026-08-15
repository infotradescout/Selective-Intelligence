#!/usr/bin/env python3
"""Build and validate one durable architecture index for a project.

The index is deliberately dependency-free. It inventories directories, source
files, exported and top-level symbols, UI primitives, raw interactive elements,
and duplicate ownership risks. Refreshing preserves the project's explicit
canonical-owner declarations and reuse decisions while replacing generated
inventory with facts from the current repository.
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

sys.dont_write_bytecode = True

SCHEMA_VERSION = 1
INDEX_VERSION = "0.1.0"
DEFAULT_INDEX = Path(".selective-intelligence/project-index.json")
SOURCE_EXTENSIONS = {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".py"}
UI_EXTENSIONS = {".jsx", ".tsx"}
SKIP_DIRECTORIES = {
    ".git",
    ".hg",
    ".svn",
    ".selective-intelligence",
    ".next",
    ".nuxt",
    ".turbo",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "target",
    "vendor",
}
PRIMITIVE_NAMES = {
    "Button",
    "Card",
    "Checkbox",
    "Dialog",
    "Drawer",
    "Field",
    "Form",
    "Input",
    "Modal",
    "Radio",
    "Select",
    "Table",
    "Tabs",
    "Textarea",
    "Toast",
    "Tooltip",
}
RAW_UI_RE = re.compile(r"<\s*(button|input|select|textarea|form)\b", re.IGNORECASE)
JS_DECLARATIONS = (
    ("class", re.compile(r"(?m)^\s*(export\s+(?:default\s+)?)?class\s+([A-Za-z_$][\w$]*)")),
    ("function", re.compile(r"(?m)^\s*(export\s+(?:default\s+)?)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(")),
    ("function", re.compile(r"(?m)^\s*(export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^\n]*\)|[A-Za-z_$][\w$]*)\s*=>")),
    ("type", re.compile(r"(?m)^\s*(export\s+)?(?:interface|type|enum)\s+([A-Za-z_$][\w$]*)")),
)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def json_digest(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return sha256_bytes(payload)


def safe_relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def source_files(root: Path) -> Iterable[Path]:
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        directories[:] = sorted(
            name
            for name in directories
            if name not in SKIP_DIRECTORIES and not (current_path / name).is_symlink()
        )
        for name in sorted(files):
            path = current_path / name
            if path.suffix.lower() in SOURCE_EXTENSIONS and not path.is_symlink():
                yield path


def line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def classify_symbol(name: str, declared_kind: str, suffix: str) -> str:
    if name.startswith("use") and len(name) > 3 and name[3].isupper():
        return "hook"
    if suffix in UI_EXTENSIONS and name[:1].isupper() and declared_kind in {"class", "function"}:
        return "component"
    return declared_kind


def javascript_symbols(relative: str, text: str, suffix: str) -> list[dict[str, Any]]:
    symbols: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for declared_kind, pattern in JS_DECLARATIONS:
        for match in pattern.finditer(text):
            name = match.group(2)
            line = line_number(text, match.start())
            key = (name, line)
            if key in seen:
                continue
            seen.add(key)
            symbols.append(
                {
                    "name": name,
                    "kind": classify_symbol(name, declared_kind, suffix),
                    "path": relative,
                    "line": line,
                    "exported": bool(match.group(1)),
                }
            )
    return symbols


def python_symbols(relative: str, text: str) -> list[dict[str, Any]]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    symbols: list[dict[str, Any]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            kind = "class" if isinstance(node, ast.ClassDef) else classify_symbol(node.name, "function", ".py")
            symbols.append(
                {
                    "name": node.name,
                    "kind": kind,
                    "path": relative,
                    "line": int(getattr(node, "lineno", 1)),
                    "exported": not node.name.startswith("_"),
                }
            )
    return symbols


def git_facts(root: Path) -> dict[str, Any]:
    def run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )

    inside = run("rev-parse", "--is-inside-work-tree")
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        return {"kind": "directory", "revision": None, "dirty": None}
    revision = run("rev-parse", "HEAD")
    status = run("status", "--porcelain", "--untracked-files=normal")
    dirty_lines = []
    if status.returncode == 0:
        dirty_lines = [
            line
            for line in status.stdout.splitlines()
            if not line.replace("\\", "/").endswith(DEFAULT_INDEX.as_posix())
        ]
    return {
        "kind": "git",
        "revision": revision.stdout.strip() if revision.returncode == 0 else None,
        "dirty": bool(dirty_lines) if status.returncode == 0 else None,
    }


def retained_governance(existing: object) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    default = {"directories": [], "ui_primitives": [], "shared_symbols": []}
    if not isinstance(existing, dict):
        return default, []
    canonical = existing.get("canonical")
    decisions = existing.get("reuse_decisions")
    if not isinstance(canonical, dict):
        canonical = default
    clean_canonical: dict[str, list[dict[str, Any]]] = {}
    for key in default:
        value = canonical.get(key)
        clean_canonical[key] = value if isinstance(value, list) and all(isinstance(item, dict) for item in value) else []
    clean_decisions = decisions if isinstance(decisions, list) and all(isinstance(item, dict) for item in decisions) else []
    return clean_canonical, clean_decisions


def load_existing(path: Path) -> object:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def declared_generated_projections(root: Path) -> list[dict[str, str]]:
    """Read bounded adapter manifests that name one canonical source and projection.

    Generated adapters are intentional mirrors, not competing owners. The
    exception is accepted only when a repository manifest explicitly names
    both roots and duplicate paths have the same suffix below those roots.
    """
    projections: list[dict[str, str]] = []
    for manifest in sorted(root.glob("adapters/**/metadata/*-adapter.json")):
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        source = data.get("portable_source_path")
        destination = data.get("adapter_path")
        if not isinstance(source, str) or not isinstance(destination, str):
            continue
        source_path = Path(source)
        destination_path = Path(destination)
        if (
            source_path.is_absolute()
            or destination_path.is_absolute()
            or ".." in source_path.parts
            or ".." in destination_path.parts
        ):
            continue
        source_value = source_path.as_posix().strip("/")
        destination_value = destination_path.as_posix().strip("/")
        if not source_value or not destination_value or source_value == destination_value:
            continue
        if not (root / source_path).is_dir() or not (root / destination_path).is_dir():
            continue
        projections.append(
            {
                "canonical": source_value,
                "projection": destination_value,
                "manifest": safe_relative(root, manifest),
            }
        )
    return projections


def generated_projection_exception(paths: list[str], projections: list[dict[str, str]]) -> dict[str, str] | None:
    if len(paths) != 2:
        return None
    for projection in projections:
        canonical_prefix = projection["canonical"] + "/"
        adapter_prefix = projection["projection"] + "/"
        canonical_paths = [path for path in paths if path.startswith(canonical_prefix)]
        adapter_paths = [path for path in paths if path.startswith(adapter_prefix)]
        if len(canonical_paths) != 1 or len(adapter_paths) != 1:
            continue
        canonical_suffix = canonical_paths[0][len(canonical_prefix) :]
        adapter_suffix = adapter_paths[0][len(adapter_prefix) :]
        if canonical_suffix == adapter_suffix:
            return projection
    return None


def build_index(root: Path, existing: object = None) -> dict[str, Any]:
    root = root.resolve()
    canonical, reuse_decisions = retained_governance(existing)
    files: list[dict[str, Any]] = []
    symbols: list[dict[str, Any]] = []
    raw_ui: list[dict[str, Any]] = []
    directory_counts: Counter[str] = Counter()
    hash_paths: defaultdict[str, list[str]] = defaultdict(list)

    for path in source_files(root):
        relative = safe_relative(root, path)
        try:
            payload = path.read_bytes()
        except OSError:
            continue
        if len(payload) > 2 * 1024 * 1024:
            continue
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError:
            continue
        digest = sha256_bytes(payload)
        suffix = path.suffix.lower()
        files.append({"path": relative, "language": suffix.removeprefix("."), "sha256": digest, "bytes": len(payload)})
        hash_paths[digest].append(relative)
        directory_counts[Path(relative).parent.as_posix()] += 1
        symbols.extend(python_symbols(relative, text) if suffix == ".py" else javascript_symbols(relative, text, suffix))
        if suffix in UI_EXTENSIONS:
            for match in RAW_UI_RE.finditer(text):
                raw_ui.append({"tag": match.group(1).lower(), "path": relative, "line": line_number(text, match.start())})

    files.sort(key=lambda item: item["path"])
    symbols.sort(key=lambda item: (item["path"], item["line"], item["name"]))
    raw_ui.sort(key=lambda item: (item["path"], item["line"], item["tag"]))
    directories = [
        {"path": path, "source_file_count": count}
        for path, count in sorted(directory_counts.items())
    ]
    duplicate_files = [
        {"sha256": digest, "paths": sorted(paths)}
        for digest, paths in sorted(hash_paths.items())
        if len(paths) > 1
    ]
    exported_by_name: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for symbol in symbols:
        if symbol["exported"] and symbol["kind"] in {"component", "hook"}:
            exported_by_name[symbol["name"]].append(symbol)
    symbol_collisions = [
        {"name": name, "owners": [{"path": item["path"], "line": item["line"], "kind": item["kind"]} for item in owners]}
        for name, owners in sorted(exported_by_name.items())
        if len({item["path"] for item in owners}) > 1
    ]
    ui_candidates = [
        {"name": symbol["name"], "path": symbol["path"], "line": symbol["line"]}
        for symbol in symbols
        if symbol["kind"] == "component"
        and (
            symbol["name"] in PRIMITIVE_NAMES
            or any(part in {"ui", "primitives", "design-system"} for part in Path(symbol["path"]).parts)
        )
    ]
    raw_paths_by_tag: defaultdict[str, set[str]] = defaultdict(set)
    for item in raw_ui:
        raw_paths_by_tag[item["tag"]].add(item["path"])

    projections = declared_generated_projections(root)
    justified_duplicates: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    for group in duplicate_files:
        exception = generated_projection_exception(group["paths"], projections)
        if exception is not None:
            justified_duplicates.append({**group, "exception": exception})
            continue
        findings.append({"severity": "error", "code": "PI001", "message": "Exact duplicate source files require consolidation or an explicit exception.", "paths": group["paths"]})
    for collision in symbol_collisions:
        findings.append({"severity": "error", "code": "PI002", "message": f"Exported symbol {collision['name']} has multiple candidate owners.", "paths": [item["path"] for item in collision["owners"]]})
    for tag, paths in sorted(raw_paths_by_tag.items()):
        if len(paths) >= 3:
            findings.append({"severity": "warning", "code": "PI003", "message": f"Raw <{tag}> markup is spread across {len(paths)} files; reuse or establish one canonical primitive before adding another variant.", "paths": sorted(paths)})
    known_paths = {item["path"] for item in files}
    for section in ("ui_primitives", "shared_symbols"):
        for declaration in canonical[section]:
            path = declaration.get("path")
            if not isinstance(path, str) or path not in known_paths:
                findings.append({"severity": "error", "code": "PI004", "message": f"Canonical {section} declaration points to a missing source file.", "paths": [str(path)]})
    known_directories = {item["path"] for item in directories}
    for declaration in canonical["directories"]:
        path = declaration.get("path")
        if not isinstance(path, str) or path not in known_directories:
            findings.append({"severity": "error", "code": "PI005", "message": "Canonical directory declaration points to a missing source directory.", "paths": [str(path)]})

    inventory = {
        "directories": directories,
        "files": files,
        "symbols": symbols,
        "ui": {"primitive_candidates": ui_candidates, "raw_elements": raw_ui},
        "duplicates": {
            "exact_files": duplicate_files,
            "justified_generated_projections": justified_duplicates,
            "exported_symbol_collisions": symbol_collisions,
        },
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "index_version": INDEX_VERSION,
        "generated_at": utc_now(),
        "source": {**git_facts(root), "inventory_sha256": json_digest(inventory)},
        "inventory": inventory,
        "canonical": canonical,
        "reuse_decisions": reuse_decisions,
        "findings": findings,
        "summary": {
            "directories": len(directories),
            "source_files": len(files),
            "symbols": len(symbols),
            "components": sum(item["kind"] == "component" for item in symbols),
            "functions_and_hooks": sum(item["kind"] in {"function", "hook"} for item in symbols),
            "raw_ui_elements": len(raw_ui),
            "errors": sum(item["severity"] == "error" for item in findings),
            "warnings": sum(item["severity"] == "warning" for item in findings),
        },
    }


def resolve_index_path(root: Path, output: str | None) -> Path:
    root = root.resolve()
    candidate = Path(output) if output else DEFAULT_INDEX
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved_parent = candidate.parent.resolve()
    if resolved_parent != root and root not in resolved_parent.parents:
        raise ValueError("project index output must stay inside the project root")
    if candidate.exists() and candidate.is_symlink():
        raise ValueError("project index output may not be a symlink")
    return candidate


def write_index(root: Path, output: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    output = output or (root / DEFAULT_INDEX)
    output.parent.mkdir(parents=True, exist_ok=True)
    index = build_index(root, load_existing(output))
    payload = json.dumps(index, indent=2, ensure_ascii=False) + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=output.parent, delete=False, newline="\n") as handle:
        handle.write(payload)
        temporary = Path(handle.name)
    temporary.replace(output)
    return index


def doctor(root: Path, output: Path, strict: bool = False) -> tuple[dict[str, Any], int]:
    existing = load_existing(output)
    if not isinstance(existing, dict):
        result = {"ready": False, "stale": True, "errors": ["project index is missing or invalid"], "warnings": [], "summary": {}}
        return result, 1
    fresh = build_index(root, existing)
    stale = existing.get("source", {}).get("inventory_sha256") != fresh["source"]["inventory_sha256"]
    errors = [item["message"] for item in fresh["findings"] if item["severity"] == "error"]
    warnings = [item["message"] for item in fresh["findings"] if item["severity"] == "warning"]
    if stale:
        errors.insert(0, "project index is stale; refresh it before creating or moving code")
    result = {"ready": not errors and not (strict and warnings), "stale": stale, "errors": errors, "warnings": warnings, "summary": fresh["summary"]}
    return result, 1 if errors or (strict and warnings) else 0


def command_refresh(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    output = resolve_index_path(root, args.output)
    index = write_index(root, output)
    result = {"written": safe_relative(root, output), "source": index["source"], "summary": index["summary"]}
    print(json.dumps(result, indent=2) if args.json else f"Refreshed {result['written']}: {json.dumps(result['summary'], sort_keys=True)}")
    return 0


def command_doctor(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    output = resolve_index_path(root, args.output)
    result, code = doctor(root, output, args.strict)
    print(json.dumps(result, indent=2) if args.json else ("Project index is ready." if code == 0 else "Project index requires attention."))
    if not args.json:
        for item in result["errors"]:
            print(f"ERROR: {item}")
        for item in result["warnings"]:
            print(f"WARNING: {item}")
    return code


def command_self_test(_: argparse.Namespace) -> int:
    with tempfile.TemporaryDirectory(prefix="selective-intelligence-project-index-") as temporary:
        root = Path(temporary)
        (root / "src/components/ui").mkdir(parents=True)
        (root / "src/features/checkout").mkdir(parents=True)
        (root / "src/lib").mkdir(parents=True)
        (root / "src/components/ui/Button.tsx").write_text("export function Button() { return <button>Go</button>; }\n", encoding="utf-8")
        (root / "src/features/checkout/Checkout.tsx").write_text("export const Checkout = () => <button>Pay</button>;\n", encoding="utf-8")
        (root / "src/features/checkout/Retry.tsx").write_text("export const Retry = () => <button>Retry</button>;\n", encoding="utf-8")
        (root / "src/features/checkout/Cancel.tsx").write_text("export const Cancel = () => <button>Cancel</button>;\n", encoding="utf-8")
        (root / "src/features/checkout/Button.tsx").write_text("export function Button() { return <button>Feature</button>; }\n", encoding="utf-8")
        (root / "src/lib/money.py").write_text("def format_money(value):\n    return f'${value}'\n", encoding="utf-8")
        output = root / DEFAULT_INDEX
        first = write_index(root, output)
        if first["summary"]["components"] != 5 or first["summary"]["functions_and_hooks"] != 1:
            raise AssertionError("project index did not classify representative components and functions")
        if not any(item["code"] == "PI003" for item in first["findings"]):
            raise AssertionError("project index did not flag raw UI proliferation")
        if not any(item["code"] == "PI002" for item in first["findings"]):
            raise AssertionError("project index did not flag competing component owners")
        checked, checked_code = doctor(root, output)
        if checked_code != 1 or checked["stale"]:
            raise AssertionError("fresh project index did not preserve component-owner findings")
        (root / "src/lib/money.py").write_text("def format_money(value):\n    return f'USD {value}'\n", encoding="utf-8")
        stale, stale_code = doctor(root, output)
        if stale_code != 1 or not stale["stale"]:
            raise AssertionError("project index did not detect source drift")

        projection_root = root / "projection-fixture"
        canonical = projection_root / "skills/example/scripts"
        adapter = projection_root / "adapters/chatgpt/example/scripts"
        metadata = projection_root / "adapters/chatgpt/example/metadata"
        canonical.mkdir(parents=True)
        adapter.mkdir(parents=True)
        metadata.mkdir(parents=True)
        payload = "def shared_owner():\n    return True\n"
        (canonical / "owner.py").write_text(payload, encoding="utf-8")
        (adapter / "owner.py").write_text(payload, encoding="utf-8")
        (metadata / "chatgpt-adapter.json").write_text(
            json.dumps(
                {
                    "portable_source_path": "skills/example",
                    "adapter_path": "adapters/chatgpt/example",
                }
            ),
            encoding="utf-8",
        )
        projected = build_index(projection_root)
        if any(item["code"] == "PI001" for item in projected["findings"]):
            raise AssertionError("declared generated projection was treated as a competing owner")
        if len(projected["inventory"]["duplicates"]["justified_generated_projections"]) != 1:
            raise AssertionError("generated projection exception was not recorded")
        (projection_root / "rogue.py").write_text(payload, encoding="utf-8")
        rogue = build_index(projection_root)
        if not any(item["code"] == "PI001" for item in rogue["findings"]):
            raise AssertionError("undeclared third duplicate did not fail closed")
    print(json.dumps({"passed": True, "index_version": INDEX_VERSION, "checks": ["inventory", "ui-proliferation", "freshness", "generated-projection-boundary"]}, indent=2))
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Generate one project directory, function, component, and reuse index")
    commands = root.add_subparsers(dest="command", required=True)
    refresh = commands.add_parser("refresh")
    refresh.add_argument("--root", default=".")
    refresh.add_argument("--output")
    refresh.add_argument("--json", action="store_true")
    refresh.set_defaults(func=command_refresh)
    check = commands.add_parser("doctor")
    check.add_argument("--root", default=".")
    check.add_argument("--output")
    check.add_argument("--strict", action="store_true")
    check.add_argument("--json", action="store_true")
    check.set_defaults(func=command_doctor)
    self_test = commands.add_parser("self-test")
    self_test.set_defaults(func=command_self_test)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        return args.func(args)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
