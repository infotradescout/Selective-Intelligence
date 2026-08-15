#!/usr/bin/env python3
"""Deterministic first-deliverable checks for small static websites.

This is deliberately a local quality gate, not a claim that a model produced a
good design. It checks the rendered source package for basic completeness
without a paid service, account, network call, or project-specific prompt.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


PLACEHOLDERS = re.compile(
    r"\b(?:lorem ipsum|todo|tbd|your company|your business|coming soon)\b|(?:https?://)?example\.com",
    re.I,
)
RESPONSIVE_CSS = re.compile(r"@media\b|\b(?:clamp|minmax)\s*\(|\b(?:vw|vh|dvw|dvh)\b", re.I)


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[tuple[str, dict[str, str]]] = []
        self.title_parts: list[str] = []
        self.visible_text: list[str] = []
        self._in_title = False
        self._hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name.lower(): value or "" for name, value in attrs}
        tag = tag.lower()
        self.tags.append((tag, values))
        if tag == "title":
            self._in_title = True
        if tag in {"script", "style", "template"}:
            self._hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title":
            self._in_title = False
        if tag in {"script", "style", "template"} and self._hidden_depth:
            self._hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if not text:
            return
        if self._in_title:
            self.title_parts.append(text)
        if not self._hidden_depth:
            self.visible_text.append(text)


def _result(name: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"check": name, "passed": passed, "detail": detail}


def audit_site(root: Path) -> dict[str, Any]:
    root = root.resolve()
    root_label = root.name or "."
    index = root / "index.html"
    if not index.is_file():
        return {
            "schemaVersion": "si.site_quality.v1",
            "root": root_label,
            "passed": False,
            "checks": [_result("index_html", False, "index.html is missing")],
        }

    raw = index.read_bytes()
    text = raw.decode("utf-8")
    parser = PageParser()
    parser.feed(text)
    tags = parser.tags

    html_attrs = next((attrs for tag, attrs in tags if tag == "html"), {})
    metas = [attrs for tag, attrs in tags if tag == "meta"]
    links = [attrs for tag, attrs in tags if tag == "a"]
    images = [attrs for tag, attrs in tags if tag == "img"]
    styles = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in sorted(root.rglob("*.css"))
        if path.is_file()
    ) + "\n" + text

    viewport = any(meta.get("name", "").lower() == "viewport" and "width=device-width" in meta.get("content", "").lower() for meta in metas)
    description = next((meta.get("content", "").strip() for meta in metas if meta.get("name", "").lower() == "description"), "")
    local_broken: list[str] = []
    placeholder_links: list[str] = []
    for attrs in links:
        href = attrs.get("href", "").strip()
        if not href or href == "#" or href.lower().startswith("javascript:"):
            placeholder_links.append(href or "(empty)")
            continue
        if href.startswith(("#", "mailto:", "tel:", "http://", "https://", "/")):
            continue
        target = href.split("#", 1)[0].split("?", 1)[0]
        if target and not (root / target).is_file():
            local_broken.append(href)

    action_count = sum(1 for tag, attrs in tags if tag == "button" or (tag == "a" and attrs.get("href", "").strip() not in {"", "#"}))
    h1_count = sum(1 for tag, _ in tags if tag == "h1")
    checks = [
        _result("index_html", True, "index.html found"),
        _result("language", bool(html_attrs.get("lang", "").strip()), "html lang is set" if html_attrs.get("lang", "").strip() else "html lang is missing"),
        _result("title", bool(" ".join(parser.title_parts).strip()), "page title is set" if parser.title_parts else "page title is missing"),
        _result("description", len(description) >= 30, "meta description is substantive" if len(description) >= 30 else "meta description is missing or too short"),
        _result("viewport", viewport, "mobile viewport is set" if viewport else "mobile viewport is missing"),
        _result("main_landmark", any(tag == "main" for tag, _ in tags), "main landmark found" if any(tag == "main" for tag, _ in tags) else "main landmark is missing"),
        _result("single_h1", h1_count == 1, f"found {h1_count} h1 element(s)"),
        _result("usable_action", action_count > 0, f"found {action_count} usable action(s)"),
        _result("links", not placeholder_links and not local_broken, f"placeholder={placeholder_links}; broken_local={local_broken}"),
        _result("image_alt", all("alt" in attrs for attrs in images), "all images declare alt text" if all("alt" in attrs for attrs in images) else "one or more images lack alt text"),
        _result("responsive_css", bool(RESPONSIVE_CSS.search(styles)), "responsive CSS signal found" if RESPONSIVE_CSS.search(styles) else "no responsive CSS signal found"),
        _result("no_placeholders", not PLACEHOLDERS.search(" ".join(parser.visible_text)), "no visible placeholder copy found" if not PLACEHOLDERS.search(" ".join(parser.visible_text)) else "visible placeholder copy found"),
    ]
    passed = all(check["passed"] for check in checks)
    return {
        "schemaVersion": "si.site_quality.v1",
        "root": root_label,
        "artifact": {"path": "index.html", "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()},
        "passed": passed,
        "passedChecks": sum(check["passed"] for check in checks),
        "totalChecks": len(checks),
        "checks": checks,
        "boundary": "deterministic package checks; visual quality still requires rendered inspection",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit a static website first deliverable without paid services")
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument("--output")
    args = parser.parse_args()
    result = audit_site(Path(args.root))
    payload = json.dumps(result, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
