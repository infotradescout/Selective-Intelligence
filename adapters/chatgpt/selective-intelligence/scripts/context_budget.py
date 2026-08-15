#!/usr/bin/env python3
"""Select a small, task-aware, secret-safe repository context bundle."""
from __future__ import annotations

import ast
import hashlib
import json
import posixpath
import re
from pathlib import Path
from typing import Any, Mapping, Sequence


EXCLUDED_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".cache", "dist", "build"}
SENSITIVE_NAME_PATTERNS = (
    re.compile(r"^\.env(?:\..+)?$", re.I),
    re.compile(r"(?:secret|credential|token|private[_-]?key)", re.I),
    re.compile(r"(?:^|[._-])id_rsa(?:$|[._-])", re.I),
    re.compile(r"\.(?:pem|p12|pfx|key)$", re.I),
)
SENSITIVE_CONTENT = re.compile(
    r"BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY"
    r"|(?:api[_-]?key|secret|token|password|aws[_-]?secret[_-]?access[_-]?key)\s*[:=]\s*['\"]?[^\s'\"]{8,}"
    r"|authorization\s*:\s*bearer\s+[A-Za-z0-9._~+/=-]{8,}"
    r"|\b(?:AKIA|ASIA|AIDA|AROA)[A-Z0-9]{16}\b"
    r"|\bgithub_pat_[A-Za-z0-9_]{20,255}\b"
    r"|\bgh[pousr]_[A-Za-z0-9_]{20,255}\b"
    r"|\bxox[baprs]-[A-Za-z0-9-]{10,}\b"
    r"|\bsk-[A-Za-z0-9_-]{20,}\b"
    r"|\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b",
    re.I,
)
JS_DEPENDENCY = re.compile(r"(?:\bfrom\s*|\brequire\s*\(\s*|\bimport\s*\(\s*)['\"](\.[^'\"]+)['\"]")
SOURCE_SUFFIXES = (".py", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx")
TOKEN_RE = re.compile(r"[A-Za-z0-9]{2,}")
STOP_WORDS = {
    "and", "are", "but", "change", "code", "for", "from", "into", "only", "that", "the", "then",
    "this", "with", "without", "work", "working",
}


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _estimated_tokens(payload: bytes) -> int:
    return (len(payload) + 3) // 4


def _terms(value: object) -> set[str]:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(value or ""))
    return {term.lower() for term in TOKEN_RE.findall(text) if term.lower() not in STOP_WORDS}


def _task_text(task: Mapping[str, Any] | str | None) -> str:
    if isinstance(task, str):
        return task
    if not isinstance(task, Mapping):
        return ""
    values: list[str] = []
    for key in ("title", "key"):
        value = task.get(key)
        if isinstance(value, str):
            values.append(value)
    for key in ("tags", "intentRefs"):
        value = task.get(key)
        if isinstance(value, list):
            values.extend(item for item in value if isinstance(item, str))
    metadata = task.get("metadata")
    if isinstance(metadata, Mapping) and isinstance(metadata.get("planKey"), str):
        values.append(metadata["planKey"])
    return " ".join(values)


def _acceptance_refs(task: Mapping[str, Any] | str | None, refs: Sequence[str] | None) -> list[str]:
    values = [item for item in (refs or []) if isinstance(item, str) and item.strip()]
    if isinstance(task, Mapping) and isinstance(task.get("acceptanceRefs"), list):
        values.extend(item for item in task["acceptanceRefs"] if isinstance(item, str) and item.strip())
    return list(dict.fromkeys(values))


def _contains_path(text: str, relative: str) -> bool:
    normalized = text.replace("\\", "/").lower()
    variants = (relative.lower(), Path(relative).name.lower())
    return any(
        re.search(rf"(?<![\w./-]){re.escape(value)}(?![\w./-])", normalized)
        for value in variants
    )


def _selection_reason(candidate: dict[str, Any]) -> str:
    sources = candidate["explicitSources"]
    if "acceptance" in sources:
        return "explicit acceptance reference"
    if "task" in sources:
        return "explicit task reference"
    if "objective" in sources:
        return "explicit objective reference"
    relations = candidate.get("relationSources", [])
    if relations:
        return "; ".join(relations[:3])
    path_hits = candidate["pathHits"]
    content_hits = candidate["contentHits"]
    if path_hits or content_hits:
        signals = []
        if path_hits:
            signals.append("path=" + ",".join(path_hits[:5]))
        if content_hits:
            signals.append("content=" + ",".join(content_hits[:5]))
        return "task relevance: " + "; ".join(signals)
    return "bounded fallback when no task relevance signal exists"


def _looks_like_path(value: str) -> bool:
    normalized = value.replace("\\", "/")
    return "/" in normalized or bool(Path(normalized).suffix)


def _resolve_module(parts: Sequence[str], candidates: set[str]) -> set[str]:
    if not parts:
        return set()
    stem = "/".join(parts)
    targets = {stem + ".py", stem + "/__init__.py"}
    resolved = {path for path in candidates if path in targets}
    if resolved:
        return resolved
    return {path for path in candidates if any(path.endswith("/" + target) for target in targets)}


def _python_dependencies(relative: str, text: str, candidates: set[str]) -> set[str]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return set()
    parent = list(Path(relative).parent.parts)
    dependencies: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                dependencies.update(_resolve_module(alias.name.split("."), candidates))
        elif isinstance(node, ast.ImportFrom):
            base = [] if node.level == 0 else parent[: max(0, len(parent) - (node.level - 1))]
            module = node.module.split(".") if node.module else []
            dependencies.update(_resolve_module([*base, *module], candidates))
            for alias in node.names:
                if alias.name != "*":
                    dependencies.update(_resolve_module([*base, *module, *alias.name.split(".")], candidates))
    dependencies.discard(relative)
    return dependencies


def _javascript_dependencies(relative: str, text: str, candidates: set[str]) -> set[str]:
    parent = Path(relative).parent.as_posix()
    dependencies: set[str] = set()
    for specifier in JS_DEPENDENCY.findall(text):
        stem = posixpath.normpath(posixpath.join(parent, specifier))
        targets = {stem, *(stem + suffix for suffix in SOURCE_SUFFIXES)}
        targets.update(stem + "/index" + suffix for suffix in SOURCE_SUFFIXES)
        dependencies.update(path for path in candidates if path in targets)
    dependencies.discard(relative)
    return dependencies


def _local_dependencies(relative: str, text: str, candidates: set[str]) -> set[str]:
    suffix = Path(relative).suffix.lower()
    if suffix == ".py":
        return _python_dependencies(relative, text, candidates)
    if suffix in SOURCE_SUFFIXES[1:]:
        return _javascript_dependencies(relative, text, candidates)
    return set()


def _canonical_owner_paths(workspace: Path, query_terms: set[str], candidates: set[str]) -> set[str]:
    index_path = workspace / ".selective-intelligence" / "project-index.json"
    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    canonical = data.get("canonical")
    if not isinstance(canonical, Mapping):
        return set()
    owners: set[str] = set()
    for declarations in canonical.values():
        if not isinstance(declarations, list):
            continue
        for declaration in declarations:
            if not isinstance(declaration, Mapping):
                continue
            path = declaration.get("path")
            if not isinstance(path, str) or path not in candidates:
                continue
            descriptor = " ".join(str(value) for key, value in declaration.items() if key != "path")
            if query_terms & _terms(descriptor + " " + path):
                owners.add(path)
    return owners


def select_context(
    workspace: Path,
    *,
    objective: str = "",
    task: Mapping[str, Any] | str | None = None,
    acceptance_refs: Sequence[str] | None = None,
    max_files: int = 50,
    max_bytes: int = 65536,
    max_file_bytes: int = 16384,
) -> dict[str, Any]:
    """Return exact references first, then task-relevant safe text within hard limits."""
    for name, value in (("max_files", max_files), ("max_bytes", max_bytes), ("max_file_bytes", max_file_bytes)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} must be a non-negative integer")

    workspace = Path(workspace).resolve()
    task_text = _task_text(task)
    refs = _acceptance_refs(task, acceptance_refs)
    query_terms = _terms(" ".join([objective, task_text, *refs]))
    candidates: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    avoided_tokens = 0
    referenced_workspace_paths: set[str] = set()

    for path in sorted(workspace.rglob("*")):
        if not path.is_file():
            continue
        relative_path = path.relative_to(workspace)
        relative = relative_path.as_posix()
        if any(_contains_path(ref, relative) for ref in refs):
            referenced_workspace_paths.add(relative)
        if path.is_symlink():
            excluded.append({"path": relative, "reason": "symlink excluded"})
            continue
        if relative_path.parts[:2] == (".selective-intelligence", "feedback"):
            excluded.append({"path": relative, "reason": "private feedback store excluded"})
            continue
        if any(part.lower() in EXCLUDED_DIRS for part in relative_path.parts):
            excluded.append({"path": relative, "reason": "excluded directory"})
            continue
        if any(pattern.search(path.name) for pattern in SENSITIVE_NAME_PATTERNS):
            excluded.append({"path": relative, "reason": "sensitive filename"})
            continue
        try:
            raw = path.read_bytes()
        except OSError as exc:
            excluded.append({"path": relative, "reason": f"read failed: {type(exc).__name__}"})
            continue
        digest = _sha256(raw)
        if len(raw) > max_file_bytes:
            excluded.append({"path": relative, "reason": "file exceeds context file budget", "sha256": digest})
            avoided_tokens += _estimated_tokens(raw)
            continue
        if b"\x00" in raw:
            excluded.append({"path": relative, "reason": "binary or non-UTF-8", "sha256": digest})
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            excluded.append({"path": relative, "reason": "binary or non-UTF-8", "sha256": digest})
            continue
        if SENSITIVE_CONTENT.search(text):
            excluded.append({"path": relative, "reason": "potential secret content", "sha256": digest})
            continue

        explicit_sources: set[str] = set()
        if any(_contains_path(ref, relative) for ref in refs):
            explicit_sources.add("acceptance")
        if _contains_path(task_text, relative):
            explicit_sources.add("task")
        if _contains_path(objective, relative):
            explicit_sources.add("objective")
        path_hits = sorted(query_terms & _terms(relative))
        content_hits = sorted(query_terms & _terms(text))
        score = len(path_hits) * 100 + len(content_hits) * 5
        priority = 0 if "acceptance" in explicit_sources else 1 if "task" in explicit_sources else 2 if "objective" in explicit_sources else 3 if score > 0 else 5
        candidates.append(
            {
                "path": relative,
                "sha256": digest,
                "bytes": len(raw),
                "content": text,
                "estimatedTokens": _estimated_tokens(raw),
                "explicitSources": sorted(explicit_sources),
                "pathHits": path_hits,
                "contentHits": content_hits,
                "relevanceScore": score,
                "priority": priority,
                "relationSources": [],
            }
        )

    candidate_map = {item["path"]: item for item in candidates}
    candidate_paths = set(candidate_map)
    dependency_map = {
        path: _local_dependencies(path, candidate["content"], candidate_paths)
        for path, candidate in candidate_map.items()
    }
    seed_paths = {
        item["path"]
        for item in candidates
        if item["priority"] < 5
    }
    queue = list(sorted(seed_paths))
    visited: set[str] = set()
    while queue:
        source = queue.pop(0)
        if source in visited:
            continue
        visited.add(source)
        for dependency in sorted(dependency_map.get(source, set())):
            candidate = candidate_map[dependency]
            relation = f"local dependency of {source}"
            if relation not in candidate["relationSources"]:
                candidate["relationSources"].append(relation)
            candidate["priority"] = min(candidate["priority"], 4)
            queue.append(dependency)
    for source, dependencies in dependency_map.items():
        for seed in sorted(seed_paths & dependencies):
            candidate = candidate_map[source]
            relation = f"direct dependent of {seed}"
            if relation not in candidate["relationSources"]:
                candidate["relationSources"].append(relation)
            candidate["priority"] = min(candidate["priority"], 4)
    canonical_owners = _canonical_owner_paths(workspace, query_terms, candidate_paths)
    for owner in sorted(canonical_owners):
        candidate = candidate_map[owner]
        candidate["relationSources"].append("canonical owner matched to task")
        candidate["priority"] = min(candidate["priority"], 3)

    candidates.sort(key=lambda item: (item["priority"], -item["relevanceScore"], item["path"]))
    has_relevance = any(item["priority"] < 5 for item in candidates)
    selected: list[dict[str, Any]] = []
    used_bytes = 0
    for candidate in candidates:
        if has_relevance and candidate["priority"] == 5:
            reason = "not relevant to bounded task context"
        elif len(selected) >= max_files:
            reason = "context bundle file budget exhausted"
        elif used_bytes + candidate["bytes"] > max_bytes:
            reason = "context bundle byte budget exhausted"
        else:
            reason = ""
        if reason:
            excluded.append({"path": candidate["path"], "reason": reason, "sha256": candidate["sha256"]})
            avoided_tokens += candidate["estimatedTokens"]
            continue
        reason = _selection_reason(candidate)
        selected.append(
            {
                "path": candidate["path"],
                "sha256": candidate["sha256"],
                "bytes": candidate["bytes"],
                "estimatedTokens": candidate["estimatedTokens"],
                "content": candidate["content"],
                "selectionReason": reason,
                "relevanceScore": candidate["relevanceScore"],
            }
        )
        used_bytes += candidate["bytes"]

    selected_tokens = sum(item["estimatedTokens"] for item in selected)
    selected_paths = {item["path"] for item in selected}
    required_paths = set(referenced_workspace_paths) | canonical_owners
    for selected_path in selected_paths:
        required_paths.update(dependency_map.get(selected_path, set()))
    unresolved_paths = sorted(required_paths - selected_paths)
    unmatched_references = sorted(
        ref
        for ref in refs
        if _looks_like_path(ref) and not any(_contains_path(ref, path) for path in referenced_workspace_paths)
    )
    digest_payload = [
        {key: item[key] for key in ("path", "sha256", "bytes", "selectionReason")}
        for item in selected
    ]
    context_digest = _sha256(json.dumps(digest_payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    excluded.sort(key=lambda item: item["path"])
    return {
        "selected": selected,
        "excluded": excluded,
        "budget": {
            "maxFiles": max_files,
            "maxBytes": max_bytes,
            "maxFileBytes": max_file_bytes,
            "usedFiles": len(selected),
            "usedBytes": used_bytes,
        },
        "estimatedTokens": {"selected": selected_tokens, "avoided": avoided_tokens},
        "contextDigest": context_digest,
        "outcomeCoverage": {
            "complete": not unresolved_paths and not unmatched_references,
            "requiredPaths": sorted(required_paths),
            "unresolvedPaths": unresolved_paths,
            "unmatchedReferences": unmatched_references,
        },
        "selectionStrategy": "explicit references, task relevance, canonical owners, and local dependency closure",
    }
