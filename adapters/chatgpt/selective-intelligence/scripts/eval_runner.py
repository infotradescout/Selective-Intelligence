#!/usr/bin/env python3
"""Model-in-the-loop eval runner for Selective Intelligence.

Runs the eval cases in ``evals/evals.json`` against a real model and grades each
``must`` / ``must_not`` assertion with a model judge, producing timestamped,
model-identified evidence. This is the runner the skill's own docs name as the blocker:
until it runs, the eval cases are declarations, not proof.

Design:
- Dependency-free (standard library ``urllib`` only), matching the other SI scripts.
- Bring-your-own key via environment — the human-layer connect step. No key, no network:
  the runner falls back to a dry run that shows exactly what it would send.
- Provider-agnostic seam; Anthropic is implemented first. Set the model via ``--model``
  or ``SI_EVAL_MODEL``; a wrong or absent id is the operator's to supply (BYO model).
- Time-aware: every result carries a UTC timestamp, the model id, and the elapsed time.

Usage:
  ANTHROPIC_API_KEY=... python eval_runner.py run --model <id>
  python eval_runner.py run --dry-run          # no key needed; prints the plan
  python eval_runner.py run --case acceptance-invent-si-with-user-layer
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
EVALS_PATH = SKILL_ROOT / "evals" / "evals.json"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"


def load_cases() -> tuple[str, list[dict]]:
    data = json.loads(EVALS_PATH.read_text(encoding="utf-8"))
    return str(data.get("skill", "selective-intelligence")), list(data.get("cases", []))


def load_skill_system(full: bool) -> str:
    """The governing context handed to the model: SKILL.md, optionally with all references."""
    parts = [(SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")]
    if full:
        for ref in sorted((SKILL_ROOT / "references").glob("*.md")):
            parts.append(f"\n\n===== references/{ref.name} =====\n\n{ref.read_text(encoding='utf-8')}")
    return "".join(parts)


def anthropic_message(system: str, user: str, model: str, key: str, max_tokens: int = 4096) -> str:
    body = json.dumps(
        {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        ANTHROPIC_URL,
        data=body,
        headers={
            "x-api-key": key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    blocks = payload.get("content", [])
    return "".join(b.get("text", "") for b in blocks if b.get("type") == "text")


JUDGE_SYSTEM = (
    "You are a strict evaluator. Given a task prompt, a model's response, and one assertion, "
    "decide whether the response satisfies the assertion. Reply with ONLY compact JSON: "
    '{"met": true|false, "why": "<=15 words"}.'
)


def judge_assertion(prompt: str, output: str, assertion: str, polarity: str, model: str, key: str) -> dict:
    user = (
        f"TASK PROMPT:\n{prompt}\n\nMODEL RESPONSE:\n{output}\n\n"
        f"ASSERTION ({polarity}): {assertion}\n\n"
        "Does the response satisfy the assertion? JSON only."
    )
    raw = anthropic_message(JUDGE_SYSTEM, user, model, key, max_tokens=200).strip()
    try:
        start, end = raw.find("{"), raw.rfind("}")
        verdict = json.loads(raw[start : end + 1]) if start >= 0 else {"met": None, "why": raw[:60]}
    except (ValueError, json.JSONDecodeError):
        verdict = {"met": None, "why": "unparseable judge output"}
    verdict["assertion"] = assertion
    verdict["polarity"] = polarity
    return verdict


def grade_case(case: dict, system: str, model: str, key: str) -> dict:
    started = time.monotonic()
    output = anthropic_message(system, case["prompt"], model, key)
    verdicts: list[dict] = []
    for a in case.get("must", []):
        verdicts.append(judge_assertion(case["prompt"], output, a, "must", model, key))
    for a in case.get("must_not", []):
        v = judge_assertion(case["prompt"], output, a, "must_not", model, key)
        # For must_not, "passed" means the assertion is NOT met.
        v["passed"] = (v["met"] is False)
        verdicts.append(v)
    for v in verdicts:
        v.setdefault("passed", v.get("met") is True)
    passed = all(v.get("passed") for v in verdicts) if verdicts else None
    return {
        "id": case.get("id"),
        "passed": passed,
        "verdicts": verdicts,
        "elapsed_seconds": round(time.monotonic() - started, 2),
        "output_chars": len(output),
    }


def command_run(args: argparse.Namespace) -> int:
    skill, cases = load_cases()
    if args.case:
        cases = [c for c in cases if c.get("id") == args.case]
        if not cases:
            print(f"no case with id {args.case!r}", file=sys.stderr)
            return 2
    system = load_skill_system(full=args.full)
    model = args.model or os.environ.get("SI_EVAL_MODEL", "")
    key = os.environ.get("ANTHROPIC_API_KEY", "")

    if args.dry_run or not key:
        reason = "dry-run requested" if args.dry_run else "no ANTHROPIC_API_KEY set (BYO key)"
        print(f"[eval_runner] {reason} — not calling the model.")
        print(f"  skill: {skill}")
        print(f"  model: {model or '(unset — pass --model or SI_EVAL_MODEL)'}")
        print(f"  system context: SKILL.md{' + all references' if args.full else ''} ({len(system)} chars)")
        print(f"  cases to run: {len(cases)}")
        for c in cases:
            print(f"    - {c.get('id')}: {len(c.get('must', []))} must / {len(c.get('must_not', []))} must_not")
        print("  supply ANTHROPIC_API_KEY and --model to produce graded evidence.")
        return 0

    if not model:
        print("no model id — pass --model or set SI_EVAL_MODEL (BYO model)", file=sys.stderr)
        return 2

    started = datetime.now(UTC)
    results = []
    for c in cases:
        try:
            results.append(grade_case(c, system, model, key))
        except urllib.error.HTTPError as exc:
            results.append({"id": c.get("id"), "passed": None, "error": f"HTTP {exc.code}: {exc.reason}"})
        except (urllib.error.URLError, TimeoutError) as exc:
            results.append({"id": c.get("id"), "passed": None, "error": str(exc)})

    report = {
        "schema_version": "si_eval_run.v1",
        "skill": skill,
        "model": model,
        "provider": "anthropic",
        "started_at": started.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "cases": results,
        "passed": sum(1 for r in results if r.get("passed") is True),
        "failed": sum(1 for r in results if r.get("passed") is False),
        "errored": sum(1 for r in results if r.get("passed") is None),
        "note": "model/client evidence — grading is model-judged and should be spot-checked by a human",
    }
    out = Path(args.out) if args.out else SKILL_ROOT / "evals" / f"run-{started.strftime('%Y%m%dT%H%M%SZ')}.json"
    out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(f"[eval_runner] wrote {out}  ({report['passed']} passed / {report['failed']} failed / {report['errored']} errored)")
    return 0 if report["failed"] == 0 and report["errored"] == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Selective Intelligence model-in-the-loop eval runner")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run eval cases against a model")
    run.add_argument("--model", default="", help="model id (or set SI_EVAL_MODEL)")
    run.add_argument("--case", default="", help="run a single case by id")
    run.add_argument("--full", action="store_true", help="include all references in the system context")
    run.add_argument("--dry-run", action="store_true", help="show the plan without calling the model")
    run.add_argument("--out", default="", help="results output path")
    run.set_defaults(func=command_run)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
