#!/usr/bin/env python3
"""Validate Selective Intelligence eval fixtures and deterministic controls."""

from __future__ import annotations

import atexit
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import Any

# Evaluation must not mutate the skill tree it is inspecting, including through
# child Python processes that would otherwise create ``__pycache__`` entries.
sys.dont_write_bytecode = True
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")


SKILL_ROOT = Path(__file__).resolve().parents[1]
EVALS_PATH = SKILL_ROOT / "evals" / "evals.json"
BEHAVIOR_SCRIPT = SKILL_ROOT / "scripts" / "behavior_eval.py"

# Keep deterministic fixture work outside the installed skill even when the
# host sets its process working directory as the system temporary root.
TEMP_PARENT = Path(os.environ.get("SI_EVAL_TEMP_PARENT", str(SKILL_ROOT.parent))).resolve()

CANONICAL_ACTIVATION_EVAL_CASES = (
    {
        "id": "master-trigger-named-responsibility-direct-activation",
        "kind": "positive_trigger",
        "prompt": "The user says: 'The product keeps drifting away from the approved merchant-onboarding journey. Audit the repository and realign it with the existing intent.' They do not type the Selective Intelligence wordmark.",
        "must": [
            "treat repository audit, realignment, and drift recovery as an unmistakable named-responsibility match",
            "activate Selective Intelligence directly without an adoption question",
            "use the current request plus active conversation context to recover the approved outcome",
            "begin the audit and realignment work",
        ],
        "must_not": [
            "ask: Use Selective Intelligence for this?",
            "wait for separate adoption approval",
            "require the exact wordmark before activation",
        ],
    },
    {
        "id": "master-trigger-adjacent-discovery-adoption",
        "kind": "positive_trigger",
        "prompt": "The current user asks for a simple pros-and-cons comparison of two apartment leases. There is no correction, dissatisfaction, failure feedback, exact wordmark, or request for a named Selective Intelligence responsibility. Verified discovery finds the canonical skill as a potentially useful but merely adjacent decision-structuring method.",
        "must": [
            "verify the canonical source",
            "explain the material benefit in one plain sentence",
            "ask exactly: Use Selective Intelligence for this?",
            "wait for explicit user approval before adoption",
        ],
        "must_not": [
            "activate from discovery alone",
            "give installation or command-line homework",
            "repeat the recommendation after a decline",
        ],
    },
    {
        "id": "master-trigger-nonsoftware-correction-email",
        "kind": "positive_trigger",
        "prompt": "Earlier in the active conversation, the user asked for a customer email that preserves the promised Friday delivery and clearly names the refund option. After receiving a draft, the user replies: 'That's not what I meant. You changed the promise and ignored the refund option.'",
        "must": [
            "treat the user's correction and dissatisfaction as direct activation in a non-software conversation",
            "use the current correction plus active conversation context to identify what failed",
            "recover the real communication outcome and correct the email",
            "continue without an adoption question",
        ],
        "must_not": [
            "ask: Use Selective Intelligence for this?",
            "require a software or product antecedent",
            "ask the user to restate the email requirements already present in context",
        ],
    },
    {
        "id": "master-trigger-nonsoftware-terse-failure",
        "kind": "positive_trigger",
        "prompt": "In the active conversation, the user was arranging a family dinner for Friday because Grandma cannot attend Saturday. After the assistant changes it to Saturday, the user replies: 'What the fuck is wrong with you? I said Friday, and Grandma cannot do Saturday.'",
        "must": [
            "treat the terse failure feedback as direct activation in any conversation domain",
            "use active conversation context to identify the scheduling failure",
            "restore Friday and preserve the stated attendance constraint",
            "continue without an adoption question",
        ],
        "must_not": [
            "ask: Use Selective Intelligence for this?",
            "require software, product, or repository context",
            "make the user repeat the already-established constraint",
        ],
    },
)


def cleanup_temp_tree(path: str) -> None:
    """Remove only a temporary tree created by this evaluator."""
    candidate = Path(path).resolve()
    if candidate == TEMP_PARENT or TEMP_PARENT not in candidate.parents:
        raise RuntimeError(f"refusing to clean an unowned evaluator path: {candidate}")
    if candidate.exists():
        shutil.rmtree(candidate)


def read_cases() -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    try:
        payload = json.loads(EVALS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [], [f"invalid eval file: {exc}"]
    if payload.get("schema_version") != 1 or payload.get("skill") != "selective-intelligence":
        errors.append("eval schema_version or skill is invalid")
    cases = payload.get("cases")
    if not isinstance(cases, list):
        return [], errors + ["cases must be an array"]
    ids: set[str] = set()
    allowed = {"positive_trigger", "negative_trigger", "safety_output", "control_output"}
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            errors.append(f"case {index} must be an object")
            continue
        case_id = case.get("id")
        if not isinstance(case_id, str) or not case_id or case_id in ids:
            errors.append(f"case {index} needs a unique id")
        else:
            ids.add(case_id)
        if case.get("kind") not in allowed:
            errors.append(f"case {case_id or index} has an invalid kind")
        if not isinstance(case.get("prompt"), str) or not case["prompt"].strip():
            errors.append(f"case {case_id or index} needs a prompt")
        for key in ("must", "must_not"):
            values = case.get(key)
            if not isinstance(values, list) or not values or any(not isinstance(item, str) or not item for item in values):
                errors.append(f"case {case_id or index}.{key} must be a non-empty string array")
    cases_by_id = {
        case.get("id"): case
        for case in cases
        if isinstance(case, dict) and isinstance(case.get("id"), str)
    }
    for expected in CANONICAL_ACTIVATION_EVAL_CASES:
        case_id = expected["id"]
        if cases_by_id.get(case_id) != expected:
            errors.append(
                f"activation eval {case_id} must match the canonical direct, adjacent, or non-software correction declaration"
            )
    counts = {kind: sum(case.get("kind") == kind for case in cases if isinstance(case, dict)) for kind in allowed}
    if counts["positive_trigger"] < 5:
        errors.append("at least five positive trigger cases are required")
    if counts["negative_trigger"] < 3:
        errors.append("at least three negative trigger cases are required")
    return cases, errors


def run(command: list[str], expected: set[int] | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, check=False, text=True, capture_output=True)
    if expected is not None and result.returncode not in expected:
        raise AssertionError(f"command returned {result.returncode}: {' '.join(command)}\n{result.stdout}\n{result.stderr}")
    return result


def refresh_control_digest(manifest: dict[str, Any]) -> None:
    canonical = {key: value for key, value in manifest.items() if key != "control_digest"}
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    manifest["control_digest"] = hashlib.sha256(payload).hexdigest()


def prepare_locked_micro(root: Path, start_pack: str, through_build: bool = True) -> Path:
    run(
        [
            sys.executable,
            start_pack,
            "init",
            "--root",
            str(root),
            "--project-id",
            "closure-eval",
            "--project-name",
            "Closure Eval",
            "--release-id",
            "r1",
            "--profile",
            "micro",
        ],
        {0},
    )
    pack = root / ".selective-intelligence"
    for path in pack.rglob("*.md"):
        path.write_text(path.read_text(encoding="utf-8").replace("UNRESOLVED", "Resolved and observable."), encoding="utf-8")
    lock_path = pack / "lock.json"
    manifest = json.loads(lock_path.read_text(encoding="utf-8"))
    manifest["release"]["smallest_complete_loop"] = "User runs the utility and receives a verified result."
    manifest["authority"]["decision_owners"]["product"] = "Project owner"
    manifest["verdicts"].update({"intent": "locked", "definition": "locked", "build": "not_started"})
    manifest["requirements"] = [
        {
            "id": "REQ-1",
            "scope": "mvp",
            "state": "specified",
            "depends_on": [],
            "owners": ["utility"],
            "actor": "Local user",
            "trigger": "Runs the command",
            "behavior": "Produces the promised result",
            "constraints": "Local and reversible",
            "negative": "Does not alter unrelated files",
            "unchanged": "Existing inputs remain unchanged",
            "acceptance": "Exit zero and exact output",
            "owner": "utility",
            "proof": "Run with a representative fixture",
        }
    ]
    manifest["decisions"] = [
        {
            "id": "DEC-1",
            "class": "release_commitment",
            "status": "accepted",
            "statement": "Ship one local command",
            "authority": "Project owner",
        }
    ]
    manifest["builds"][0].update(
        {
            "status": "planned",
            "base_revision": "no-git-initial",
            "requirements": ["REQ-1"],
            "claimed_owners": ["utility"],
        }
    )
    lock_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    run([sys.executable, start_pack, "seal", "--root", str(root), "--transition", "definition"], {0})
    if not through_build:
        return lock_path
    manifest = json.loads(lock_path.read_text(encoding="utf-8"))
    manifest["verdicts"]["build"] = "aligned"
    manifest["builds"][0]["status"] = "locked"
    lock_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    run([sys.executable, start_pack, "seal", "--root", str(root), "--transition", "build"], {0})
    return lock_path


def control_tests(include_release: bool = True) -> list[str]:
    passed: list[str] = []
    start_pack = str(SKILL_ROOT / "scripts" / "start_pack.py")
    feedback = str(SKILL_ROOT / "scripts" / "feedback.py")
    with tempfile.TemporaryDirectory(prefix="selective-intelligence-eval-", dir=TEMP_PARENT) as temporary:
        atexit.register(cleanup_temp_tree, temporary)
        root = Path(temporary)
        run(
            [
                sys.executable,
                start_pack,
                "init",
                "--root",
                str(root),
                "--project-id",
                "micro-eval",
                "--project-name",
                "Micro Eval",
                "--release-id",
                "r1",
                "--profile",
                "micro",
            ],
            {0},
        )
        result = run([sys.executable, start_pack, "validate", "--root", str(root), "--json"], {0})
        if json.loads(result.stdout):
            raise AssertionError("a fresh blocked micro pack should be structurally valid")
        passed.append("fresh blocked micro pack validates structurally")

        project_index_path = root / ".selective-intelligence" / "project-index.json"
        try:
            project_index_payload = json.loads(project_index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AssertionError(f"Start Pack did not create a valid project index: {exc}") from exc
        if project_index_payload.get("schema_version") != 1:
            raise AssertionError("Start Pack project index has the wrong schema version")
        if project_index_payload.get("summary", {}).get("source_files") != 0:
            raise AssertionError("fresh empty Start Pack project index invented source files")
        passed.append("Start Pack initializes one truthful project index")

        lock_path = root / ".selective-intelligence" / "lock.json"
        fresh_baseline = lock_path.read_text(encoding="utf-8")
        invalid_definition = json.loads(fresh_baseline)
        invalid_definition["verdicts"]["definition"] = "locked"
        invalid_definition_text = json.dumps(invalid_definition, indent=2) + "\n"
        lock_path.write_text(invalid_definition_text, encoding="utf-8")
        run([sys.executable, start_pack, "seal", "--root", str(root), "--transition", "definition"], {2})
        if lock_path.read_text(encoding="utf-8") != invalid_definition_text:
            raise AssertionError("failed Definition seal mutated the invalid input manifest")

        malformed_definition = json.loads(fresh_baseline)
        malformed_definition["verdicts"]["definition"] = "locked"
        malformed_definition["active_build"] = []
        malformed_definition_text = json.dumps(malformed_definition, indent=2) + "\n"
        lock_path.write_text(malformed_definition_text, encoding="utf-8")
        malformed_seal = run(
            [sys.executable, start_pack, "seal", "--root", str(root), "--transition", "definition"],
            {2},
        )
        if "Traceback" in malformed_seal.stderr:
            raise AssertionError("malformed Definition seal raised a traceback")
        if lock_path.read_text(encoding="utf-8") != malformed_definition_text:
            raise AssertionError("failed malformed Definition seal mutated the input manifest")
        lock_path.write_text(fresh_baseline, encoding="utf-8")
        passed.append("seal refuses an invalid Definition Lock atomically")

        missing_sources = json.loads(fresh_baseline)
        del missing_sources["authority"]["governing_sources"]
        lock_path.write_text(json.dumps(missing_sources, indent=2) + "\n", encoding="utf-8")
        result = run([sys.executable, start_pack, "validate", "--root", str(root), "--json"], {1})
        if "SP011A" not in {item["code"] for item in json.loads(result.stdout)}:
            raise AssertionError("missing governing_sources did not produce the validator/schema parity diagnostic")
        lock_path.write_text(fresh_baseline, encoding="utf-8")
        passed.append("validator enforces governing source schema parity")

        review_fields = (
            "required",
            "status",
            "evidence",
            "reviewer",
            "reviewed_at",
            "scope",
            "revision",
        )
        for field in review_fields:
            missing_review_field = json.loads(fresh_baseline)
            del missing_review_field["independent_review"][field]
            lock_path.write_text(json.dumps(missing_review_field, indent=2) + "\n", encoding="utf-8")
            result = run([sys.executable, start_pack, "validate", "--root", str(root), "--json"], {1})
            if "SP094B" not in {item["code"] for item in json.loads(result.stdout)}:
                raise AssertionError(f"missing independent_review.{field} did not produce a schema-parity diagnostic")
        invalid_review_status = json.loads(fresh_baseline)
        invalid_review_status["independent_review"]["status"] = "approved"
        lock_path.write_text(json.dumps(invalid_review_status, indent=2) + "\n", encoding="utf-8")
        result = run([sys.executable, start_pack, "validate", "--root", str(root), "--json"], {1})
        if "SP094D" not in {item["code"] for item in json.loads(result.stdout)}:
            raise AssertionError("invalid independent-review status did not produce a schema-parity diagnostic")
        invalid_review_types = json.loads(fresh_baseline)
        invalid_review_types["independent_review"]["required"] = []
        invalid_review_types["independent_review"]["evidence"] = {}
        lock_path.write_text(json.dumps(invalid_review_types, indent=2) + "\n", encoding="utf-8")
        result = run([sys.executable, start_pack, "validate", "--root", str(root), "--json"], {1})
        type_codes = {item["code"] for item in json.loads(result.stdout)}
        if not {"SP094C", "SP094E"}.issubset(type_codes):
            raise AssertionError("malformed independent-review field types did not produce portable diagnostics")
        lock_path.write_text(fresh_baseline, encoding="utf-8")
        passed.append("validator enforces independent-review required fields and status parity")

        cyclic_requirements = json.loads(fresh_baseline)
        cyclic_requirements["requirements"] = [
            {"id": "REQ-A", "scope": "later", "state": "intended", "depends_on": ["REQ-B"], "owners": []},
            {"id": "REQ-B", "scope": "later", "state": "intended", "depends_on": ["REQ-A"], "owners": []},
        ]
        lock_path.write_text(json.dumps(cyclic_requirements, indent=2) + "\n", encoding="utf-8")
        result = run([sys.executable, start_pack, "validate", "--root", str(root), "--json"], {1})
        if "SP048" not in {item["code"] for item in json.loads(result.stdout)}:
            raise AssertionError("requirement dependency cycle was not blocked")
        lock_path.write_text(fresh_baseline, encoding="utf-8")
        passed.append("requirement dependency cycles are blocked")

        manifest = json.loads(fresh_baseline)
        first = manifest["builds"][0]
        first.update({"status": "locked", "base_revision": "abc123", "claimed_owners": ["auth"]})
        second = dict(first)
        second.update({"id": "b002-auth", "contract": first["contract"], "evidence": first["evidence"]})
        manifest["builds"].append(second)
        lock_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        result = run([sys.executable, start_pack, "validate", "--root", str(root), "--json"], {1})
        codes = {item["code"] for item in json.loads(result.stdout)}
        if "SP063" not in codes:
            raise AssertionError("parallel owner collision was not blocked")
        passed.append("parallel owner collision is blocked")

        manifest["requirements"] = [
            {"id": "MALFORMED", "scope": "later", "state": "intended", "depends_on": [{}], "owners": []}
        ]
        lock_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        result = run([sys.executable, start_pack, "validate", "--root", str(root), "--json"], {1})
        if "SP045B" not in {item["code"] for item in json.loads(result.stdout)}:
            raise AssertionError("malformed requirement dependency did not produce a diagnostic")
        passed.append("malformed arrays produce diagnostics instead of tracebacks")

        closure_root = root / "closure"
        closure_lock = prepare_locked_micro(closure_root, start_pack)
        result = run([sys.executable, start_pack, "validate", "--root", str(closure_root), "--json"], {0})
        if json.loads(result.stdout):
            raise AssertionError("valid Definition and Build locks did not pass")
        passed.append("valid Definition and Build locks pass")

        definition_root = root / "definition-repeat"
        definition_lock = prepare_locked_micro(definition_root, start_pack, through_build=False)
        definition_baseline = definition_lock.read_text(encoding="utf-8")
        repeated_definition = json.loads(definition_baseline)
        repeated_definition["requirements"][0]["behavior"] = "Silently changed after Definition Lock"
        definition_lock.write_text(json.dumps(repeated_definition, indent=2) + "\n", encoding="utf-8")
        run([sys.executable, start_pack, "seal", "--root", str(definition_root), "--transition", "definition"], {2})
        definition_lock.write_text(definition_baseline, encoding="utf-8")
        passed.append("repeated Definition seal cannot bypass amendment control")

        approval_relative = "approvals/AMD-1.md"
        approval_path = definition_root / ".selective-intelligence" / approval_relative
        approval_path.parent.mkdir(parents=True, exist_ok=True)
        approval_path.write_text(
            "# Amendment approval\n\nProject owner approves the REQ-1 behavior correction for release r1.\n",
            encoding="utf-8",
        )
        approval_artifact = {
            "path": approval_relative,
            "version": "0.1.1",
            "sha256": hashlib.sha256(approval_path.read_bytes()).hexdigest(),
        }

        unauthorized_amendment = json.loads(definition_baseline)
        unauthorized_amendment["requirements"][0]["behavior"] = "Unauthorized behavior change"
        unauthorized_amendment["artifacts"].append(approval_artifact)
        unauthorized_amendment["amendments"].append(
            {
                "id": "AMD-UNAUTHORIZED",
                "authority": "self-asserted actor",
                "reason": "Attempt to alter locked behavior without prior authority",
                "created_at": "2026-07-22T12:20:00+00:00",
                "impacted_requirements": ["REQ-1"],
                "approval_evidence": approval_relative,
                "changes": {
                    "added": [],
                    "modified": ["REQ-1 behavior"],
                    "removed": [],
                    "renamed": [],
                    "unchanged": ["REQ-1 scope and ownership"],
                },
            }
        )
        unauthorized_text = json.dumps(unauthorized_amendment, indent=2) + "\n"
        definition_lock.write_text(unauthorized_text, encoding="utf-8")
        run(
            [
                sys.executable,
                start_pack,
                "seal",
                "--root",
                str(definition_root),
                "--amendment",
                "AMD-UNAUTHORIZED",
                "--transition",
                "definition",
            ],
            {2},
        )
        if definition_lock.read_text(encoding="utf-8") != unauthorized_text:
            raise AssertionError("rejected unauthorized amendment mutated the manifest")
        passed.append("amendment authority is bound to prior sealed decision owners")

        malformed_amendment = json.loads(definition_baseline)
        malformed_amendment["requirements"][0]["behavior"] = "Malformed amendment behavior change"
        malformed_amendment["artifacts"].append(approval_artifact)
        malformed_amendment["amendments"].append({"id": "AMD-MALFORMED", "authority": "Project owner"})
        malformed_text = json.dumps(malformed_amendment, indent=2) + "\n"
        definition_lock.write_text(malformed_text, encoding="utf-8")
        run(
            [
                sys.executable,
                start_pack,
                "seal",
                "--root",
                str(definition_root),
                "--amendment",
                "AMD-MALFORMED",
                "--transition",
                "definition",
            ],
            {2},
        )
        if definition_lock.read_text(encoding="utf-8") != malformed_text:
            raise AssertionError("rejected malformed amendment mutated the manifest")
        passed.append("malformed amendment cannot be sealed")

        amended_definition = json.loads(definition_baseline)
        amended_definition["requirements"][0]["behavior"] = "Produces the corrected promised result"
        amended_definition["artifacts"].append(approval_artifact)
        amended_definition["amendments"].append(
            {
                "id": "AMD-1",
                "authority": "Project owner",
                "reason": "Correct the locked behavior before implementation",
                "created_at": "2026-07-22T12:30:00+00:00",
                "impacted_requirements": ["REQ-1"],
                "approval_evidence": approval_relative,
                "changes": {
                    "added": [],
                    "modified": ["REQ-1 behavior"],
                    "removed": [],
                    "renamed": [],
                    "unchanged": ["REQ-1 scope and ownership"],
                },
            }
        )
        definition_lock.write_text(json.dumps(amended_definition, indent=2) + "\n", encoding="utf-8")
        run(
            [
                sys.executable,
                start_pack,
                "seal",
                "--root",
                str(definition_root),
                "--amendment",
                "AMD-1",
                "--transition",
                "definition",
            ],
            {0},
        )
        run([sys.executable, start_pack, "validate", "--root", str(definition_root)], {0})
        passed.append("authorized amendment can re-lock a changed Definition")

        review_root = root / "independent-review"
        run(
            [
                sys.executable,
                start_pack,
                "init",
                "--root",
                str(review_root),
                "--project-id",
                "review-eval",
                "--project-name",
                "Review Eval",
                "--release-id",
                "r1",
                "--profile",
                "high_assurance",
            ],
            {0},
        )
        review_lock = review_root / ".selective-intelligence" / "lock.json"
        review_manifest = json.loads(review_lock.read_text(encoding="utf-8"))
        review_manifest["independent_review"].update({"status": "verified", "evidence": "x"})
        review_lock.write_text(json.dumps(review_manifest, indent=2) + "\n", encoding="utf-8")
        review_result = run([sys.executable, start_pack, "validate", "--root", str(review_root), "--json"], {1})
        review_codes = {item["code"] for item in json.loads(review_result.stdout)}
        if not {"SP097", "SP097A", "SP097B", "SP097C"}.issubset(review_codes):
            raise AssertionError("weak independent-review assertion did not fail every evidence identity control")
        passed.append("independent review requires registered, scoped, revision-bound evidence")

        build_baseline = closure_lock.read_text(encoding="utf-8")
        repeated_build = json.loads(build_baseline)
        repeated_build["requirements"][0]["behavior"] = "Silently changed after Build Lock"
        closure_lock.write_text(json.dumps(repeated_build, indent=2) + "\n", encoding="utf-8")
        run([sys.executable, start_pack, "seal", "--root", str(closure_root), "--transition", "build"], {2})
        closure_lock.write_text(build_baseline, encoding="utf-8")
        passed.append("repeated Build seal cannot bypass amendment control")

        checkpoint_manifest = json.loads(closure_lock.read_text(encoding="utf-8"))
        checkpoint_manifest["builds"][0]["status"] = "interrupted"
        closure_lock.write_text(json.dumps(checkpoint_manifest, indent=2) + "\n", encoding="utf-8")
        evidence_path = closure_root / ".selective-intelligence" / checkpoint_manifest["active_build"]["evidence"]
        evidence_path.write_text(evidence_path.read_text(encoding="utf-8") + "\nInterrupted after a reversible local write.\n", encoding="utf-8")
        run([sys.executable, start_pack, "seal", "--root", str(closure_root), "--checkpoint"], {0})
        run([sys.executable, start_pack, "validate", "--root", str(closure_root)], {0})
        checkpoint_manifest = json.loads(closure_lock.read_text(encoding="utf-8"))
        checkpoint_manifest["builds"][0]["status"] = "in_progress"
        closure_lock.write_text(json.dumps(checkpoint_manifest, indent=2) + "\n", encoding="utf-8")
        run([sys.executable, start_pack, "seal", "--root", str(closure_root), "--checkpoint"], {0})
        run([sys.executable, start_pack, "validate", "--root", str(closure_root)], {0})
        passed.append("interrupted and resumed build checkpoints preserve the semantic lock")

        checkpoint_baseline = closure_lock.read_text(encoding="utf-8")
        semantic_checkpoint = json.loads(checkpoint_baseline)
        semantic_checkpoint["requirements"][0]["behavior"] = "Unauthorized checkpoint behavior"
        closure_lock.write_text(json.dumps(semantic_checkpoint, indent=2) + "\n", encoding="utf-8")
        run([sys.executable, start_pack, "seal", "--root", str(closure_root), "--checkpoint"], {2})
        closure_lock.write_text(checkpoint_baseline, encoding="utf-8")
        reconciled_checkpoint = json.loads(checkpoint_baseline)
        reconciled_checkpoint["builds"][0]["status"] = "reconciled"
        closure_lock.write_text(json.dumps(reconciled_checkpoint, indent=2) + "\n", encoding="utf-8")
        run([sys.executable, start_pack, "seal", "--root", str(closure_root), "--checkpoint"], {2})
        closure_lock.write_text(checkpoint_baseline, encoding="utf-8")
        passed.append("checkpoints reject semantic changes and reconciliation claims")

        invalidated_checkpoint = json.loads(checkpoint_baseline)
        invalidated_checkpoint["invalidated_requirements"] = ["REQ-1"]
        closure_lock.write_text(json.dumps(invalidated_checkpoint, indent=2) + "\n", encoding="utf-8")
        run([sys.executable, start_pack, "seal", "--root", str(closure_root), "--checkpoint"], {0})
        invalidated_baseline = closure_lock.read_text(encoding="utf-8")
        erased_invalidation = json.loads(invalidated_baseline)
        erased_invalidation["invalidated_requirements"] = []
        closure_lock.write_text(json.dumps(erased_invalidation, indent=2) + "\n", encoding="utf-8")
        run([sys.executable, start_pack, "seal", "--root", str(closure_root), "--checkpoint"], {2})
        closure_lock.write_text(checkpoint_baseline, encoding="utf-8")
        blocker_checkpoint = json.loads(checkpoint_baseline)
        blocker_checkpoint["material_blockers"] = [
            {"id": "BLK-1", "blocking": True, "reason": "A material authority decision is unresolved"}
        ]
        closure_lock.write_text(json.dumps(blocker_checkpoint, indent=2) + "\n", encoding="utf-8")
        run([sys.executable, start_pack, "seal", "--root", str(closure_root), "--checkpoint"], {2})
        closure_lock.write_text(checkpoint_baseline, encoding="utf-8")
        passed.append("checkpoints cannot erase invalidation or silently alter material blockers")

        forged = json.loads(checkpoint_baseline)
        forged_entry = dict(forged["seal_history"][1])
        forged_entry["sealed_at"] = "2026-07-22T13:00:00+00:00"
        forged["seal_history"].append(forged_entry)
        forged["sealed_at"] = forged_entry["sealed_at"]
        refresh_control_digest(forged)
        closure_lock.write_text(json.dumps(forged, indent=2) + "\n", encoding="utf-8")
        forged_result = run([sys.executable, start_pack, "validate", "--root", str(closure_root), "--json"], {1})
        if "SP085" not in {item["code"] for item in json.loads(forged_result.stdout)}:
            raise AssertionError("forged repeated phase history was not rejected")
        closure_lock.write_text(checkpoint_baseline, encoding="utf-8")
        passed.append("validator rejects forged repeated phase history")

        phase_baseline = closure_lock.read_text(encoding="utf-8")
        phase_jump = json.loads(phase_baseline)
        phase_jump["verdicts"].update({"as_built": "reconciled", "release": "closed"})
        phase_jump["requirements"][0]["state"] = "verified"
        phase_jump["builds"][0]["status"] = "reconciled"
        phase_jump["builds"][0]["evidence_context"] = {
            "revision": "abc123",
            "environment": "local",
            "configuration": "default",
            "role": "local user",
            "fixture": "representative fixture",
            "observed_at": "2026-07-22T12:00:00Z",
            "expected": "Exact output",
            "actual": "Exact output",
            "flaky": False,
        }
        closure_lock.write_text(json.dumps(phase_jump, indent=2) + "\n", encoding="utf-8")
        run([sys.executable, start_pack, "seal", "--root", str(closure_root), "--transition", "release"], {2})
        closure_lock.write_text(phase_baseline, encoding="utf-8")
        passed.append("release transition cannot skip as-built reconciliation")

        closure_manifest = json.loads(closure_lock.read_text(encoding="utf-8"))
        closure_manifest["release"]["smallest_complete_loop"] = "Tampered after sealing"
        closure_lock.write_text(json.dumps(closure_manifest, indent=2) + "\n", encoding="utf-8")
        result = run([sys.executable, start_pack, "validate", "--root", str(closure_root), "--json"], {1})
        if "SP002B" not in {item["code"] for item in json.loads(result.stdout)}:
            raise AssertionError("sealed control tampering was not detected")
        passed.append("sealed control tampering is detected")

        closure_manifest = json.loads(closure_lock.read_text(encoding="utf-8"))
        closure_manifest["release"]["smallest_complete_loop"] = "User runs the utility and receives a verified result."
        closure_lock.write_text(json.dumps(closure_manifest, indent=2) + "\n", encoding="utf-8")
        result = run([sys.executable, start_pack, "validate", "--root", str(closure_root), "--json"], {0})
        if json.loads(result.stdout):
            raise AssertionError("restoring sealed control content did not restore integrity")

        closure_manifest["invalidated_requirements"] = ["REQ-1"]
        closure_lock.write_text(json.dumps(closure_manifest, indent=2) + "\n", encoding="utf-8")
        run([sys.executable, start_pack, "seal", "--root", str(closure_root), "--checkpoint"], {0})
        closure_manifest = json.loads(closure_lock.read_text(encoding="utf-8"))
        closure_manifest["invalidated_requirements"] = []
        closure_manifest["verdicts"].update({"as_built": "reconciled", "release": "not_started"})
        closure_manifest["requirements"][0]["state"] = "verified"
        closure_manifest["builds"][0]["status"] = "reconciled"
        closure_manifest["builds"][0]["evidence_context"] = {
            "revision": "abc123",
            "environment": "local",
            "configuration": "default",
            "role": "local user",
            "fixture": "representative fixture",
            "observed_at": "2026-07-22T12:00:00Z",
            "expected": "Exact output",
            "actual": "Exact output",
            "flaky": False,
        }
        closure_lock.write_text(json.dumps(closure_manifest, indent=2) + "\n", encoding="utf-8")
        active_evidence = closure_root / ".selective-intelligence" / closure_manifest["active_build"]["evidence"]
        active_evidence.write_text(
            active_evidence.read_text(encoding="utf-8") + "\nRevalidated REQ-1 against the exact reconciled revision.\n",
            encoding="utf-8",
        )
        run([sys.executable, start_pack, "seal", "--root", str(closure_root), "--transition", "as-built"], {0})
        passed.append("reconciled as-built evidence can explicitly clear invalidation")
        as_built_baseline = closure_lock.read_text(encoding="utf-8")
        repeated_as_built = json.loads(as_built_baseline)
        repeated_as_built["requirements"][0]["behavior"] = "Silently changed after As-built"
        closure_lock.write_text(json.dumps(repeated_as_built, indent=2) + "\n", encoding="utf-8")
        run([sys.executable, start_pack, "seal", "--root", str(closure_root), "--transition", "as-built"], {2})
        closure_lock.write_text(as_built_baseline, encoding="utf-8")
        passed.append("repeated As-built seal cannot bypass amendment control")
        closure_manifest = json.loads(closure_lock.read_text(encoding="utf-8"))
        closure_manifest["verdicts"]["release"] = "closed"
        closure_lock.write_text(json.dumps(closure_manifest, indent=2) + "\n", encoding="utf-8")
        run([sys.executable, start_pack, "seal", "--root", str(closure_root), "--transition", "release"], {0})
        result = run([sys.executable, start_pack, "validate", "--root", str(closure_root), "--json"], {0})
        if json.loads(result.stdout):
            raise AssertionError("valid release closure did not pass")
        passed.append("release closure requires and accepts exact reconciled evidence")

        store = root / "feedback.jsonl"
        task_id = str(uuid.uuid4())
        for event, cause, attempt in (
            ("task_started", "unknown", 0),
            ("validation_passed", "status_claim", 1),
            ("user_correction", "status_claim", 2),
            ("work_reopened", "status_claim", 2),
        ):
            run(
                [
                    sys.executable,
                    feedback,
                    "record",
                    "--store",
                    str(store),
                    "--task-id",
                    task_id,
                    "--event",
                    event,
                    "--cause",
                    cause,
                    "--attempt-count",
                    str(attempt),
                ],
                {0},
            )
        summary = run([sys.executable, feedback, "summarize", "--store", str(store)], {0})
        aggregate = json.loads(summary.stdout)
        if aggregate["outcomes"].get("wrong") != 1 or aggregate["negative_cause_counts"].get("status_claim") != 2:
            raise AssertionError("feedback did not preserve negative outcome and cause signals")
        if "task_id" in aggregate or "events" in aggregate:
            raise AssertionError("aggregate exposed raw event identifiers")
        passed.append("feedback preserves negative causes without raw events")

        run(
            [
                sys.executable,
                feedback,
                "record",
                "--store",
                str(root / "uuid1.jsonl"),
                "--task-id",
                str(uuid.uuid1()),
                "--event",
                "task_started",
                "--cause",
                "unknown",
            ],
            {2},
        )
        passed.append("feedback rejects identifying UUID versions")

        shared_feedback = root / "shared-feedback"
        shared_feedback.mkdir()
        shared_feedback.chmod(0o755)
        run(
            [
                sys.executable,
                feedback,
                "record",
                "--store",
                str(shared_feedback / "custom.jsonl"),
                "--task-id",
                str(uuid.uuid4()),
                "--event",
                "task_started",
                "--cause",
                "unknown",
            ],
            {0},
        )
        # POSIX permission bits are only meaningful on POSIX; chmod is a no-op on Windows.
        if os.name == "posix" and shared_feedback.stat().st_mode & 0o777 != 0o755:
            raise AssertionError("custom feedback store changed its parent directory permissions")
        managed_store = root / "managed-project" / ".selective-intelligence" / "feedback" / "events.jsonl"
        run(
            [
                sys.executable,
                feedback,
                "record",
                "--store",
                str(managed_store),
                "--task-id",
                str(uuid.uuid4()),
                "--event",
                "task_started",
                "--cause",
                "unknown",
            ],
            {0},
        )
        if os.name == "posix" and managed_store.parent.stat().st_mode & 0o777 != 0o700:
            raise AssertionError("managed feedback directory was not protected")
        if not (managed_store.parent / ".gitignore").is_file():
            raise AssertionError("managed feedback directory lacks its ignore control")
        passed.append("feedback preserves custom parent permissions and protects managed stores")

        outside = root / "outside-feedback"
        outside.mkdir()
        linked_project = root / "linked-project"
        linked_project.mkdir()
        try:
            (linked_project / ".selective-intelligence").symlink_to(outside, target_is_directory=True)
        except OSError:
            # Windows blocks symlink creation without privilege; the symlink-rejection
            # behavior is still verified on POSIX where the test can create one.
            passed.append("feedback symlink rejection skipped (platform cannot create symlinks)")
        else:
            linked_store = linked_project / ".selective-intelligence" / "feedback" / "events.jsonl"
            run(
                [
                    sys.executable,
                    feedback,
                    "record",
                    "--store",
                    str(linked_store),
                    "--task-id",
                    str(uuid.uuid4()),
                    "--event",
                    "task_started",
                    "--cause",
                    "unknown",
                ],
                {2},
            )
            if linked_store.exists():
                raise AssertionError("feedback escaped through a symlinked ancestor")
            passed.append("feedback rejects symlinked ancestor paths")

    council_script = SKILL_ROOT / "scripts" / "council.py"
    if not council_script.is_file():
        raise AssertionError("Guided Council validator is missing")
    council_result = run([sys.executable, str(council_script), "self-test", "--json"], {0})
    try:
        council_payload = json.loads(council_result.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"Council self-test did not return JSON: {exc}") from exc
    council_passed = council_payload.get("passed") if isinstance(council_payload, dict) else None
    if (
        not isinstance(council_passed, list)
        or not council_passed
        or any(not isinstance(item, str) or not item for item in council_passed)
        or len(council_passed) != len(set(council_passed))
        or council_payload.get("count") != len(council_passed)
    ):
        raise AssertionError("Council self-test returned an inconsistent passing-control list")
    passed.extend(f"Council: {item}" for item in council_passed)

    if include_release:
        version = (SKILL_ROOT / "VERSION").read_text(encoding="utf-8").strip()
        release = run([sys.executable, str(SKILL_ROOT / "scripts" / "release.py"), "doctor", "--json"], {0})
        if not json.loads(release.stdout).get("ready"):
            raise AssertionError("local release doctor did not pass")
        passed.append("local portable release gates pass")
        with tempfile.TemporaryDirectory(prefix="selective-intelligence-release-a-", dir=TEMP_PARENT) as first_dir, tempfile.TemporaryDirectory(prefix="selective-intelligence-release-b-", dir=TEMP_PARENT) as second_dir:
            atexit.register(cleanup_temp_tree, first_dir)
            atexit.register(cleanup_temp_tree, second_dir)
            release_script = str(SKILL_ROOT / "scripts" / "release.py")
            for output in (first_dir, second_dir):
                run([sys.executable, release_script, "package", "--output-dir", output], {0})
            first_archive = Path(first_dir) / f"selective-intelligence-{version}.zip"
            second_archive = Path(second_dir) / f"selective-intelligence-{version}.zip"
            first_digest = hashlib.sha256(first_archive.read_bytes()).hexdigest()
            second_digest = hashlib.sha256(second_archive.read_bytes()).hexdigest()
            if first_digest != second_digest:
                raise AssertionError("release archives are not byte reproducible")
            with zipfile.ZipFile(first_archive) as archive:
                names = archive.namelist()
                if archive.testzip() is not None:
                    raise AssertionError("release archive contains a corrupt entry")
                if "selective-intelligence/SKILL.md" not in names or "selective-intelligence/evals/evals.json" not in names:
                    raise AssertionError("release archive is missing canonical skill files")
            if any("__pycache__" in name or name.endswith("events.jsonl") or name.endswith("/lock.json") for name in names):
                raise AssertionError("release archive leaked generated, feedback, or project lock data")
            passed.append("release archive is reproducible, complete, and privacy-safe")
        cleanup_temp_tree(first_dir)
        cleanup_temp_tree(second_dir)

        with tempfile.TemporaryDirectory(prefix="selective-intelligence-release-redteam-", dir=TEMP_PARENT) as redteam_dir:
            atexit.register(cleanup_temp_tree, redteam_dir)
            copied = Path(redteam_dir) / "skill"
            shutil.copytree(SKILL_ROOT, copied, symlinks=True)
            release_script = str(copied / "scripts" / "release.py")

            (copied / "scripts" / "eval.py").write_text("raise SystemExit(1)\n", encoding="utf-8")
            run([sys.executable, release_script, "doctor", "--json"], {1})
            shutil.copy2(SKILL_ROOT / "scripts" / "eval.py", copied / "scripts" / "eval.py")

            external = Path(redteam_dir) / "external.md"
            external.write_text("not shipped\n", encoding="utf-8")
            readme_path = copied / "README.md"
            readme_baseline = readme_path.read_text(encoding="utf-8")
            with (copied / "README.md").open("a", encoding="utf-8") as handle:
                handle.write("\n[off-root](../external.md)\n")
            run([sys.executable, release_script, "doctor", "--json"], {1})
            readme_path.write_text(readme_baseline, encoding="utf-8")
            passed.append("release gates execute controls and reject off-root links")

            jumpstart_path = copied / "JUMPSTART.md"
            jumpstart_baseline = jumpstart_path.read_text(encoding="utf-8")
            jumpstart_path.write_text(
                jumpstart_baseline.replace(
                    '"activation": "current_user_master_trigger_named_work_correction_failure_or_intentional_upload"',
                    '"activation": "repository_discovery"',
                    1,
                ),
                encoding="utf-8",
            )
            jumpstart_result = run([sys.executable, release_script, "doctor", "--json"], {1})
            jumpstart_errors = json.loads(jumpstart_result.stdout).get("errors", [])
            if not any("JUMPSTART.md bootstrap activation" in error for error in jumpstart_errors):
                raise AssertionError("release doctor accepted a self-activating JumpStart manifest")
            jumpstart_path.write_text(jumpstart_baseline, encoding="utf-8")
            passed.append("release doctor binds intentional JumpStart activation")

            jumpstart_path.write_text(
                jumpstart_baseline.replace(
                    '"master_trigger": "Selective Intelligence"',
                    '"master_trigger": "Use Selective Intelligence"',
                    1,
                ),
                encoding="utf-8",
            )
            trigger_result = run([sys.executable, release_script, "doctor", "--json"], {1})
            trigger_errors = json.loads(trigger_result.stdout).get("errors", [])
            if not any("JUMPSTART.md bootstrap master_trigger" in error for error in trigger_errors):
                raise AssertionError("release doctor accepted an alternate master trigger")
            jumpstart_path.write_text(
                jumpstart_baseline.replace(
                    '"explicit_user_approval_required": true',
                    '"explicit_user_approval_required": false',
                    1,
                ),
                encoding="utf-8",
            )
            adoption_result = run([sys.executable, release_script, "doctor", "--json"], {1})
            adoption_errors = json.loads(adoption_result.stdout).get("errors", [])
            if not any("reserve the approval question for merely adjacent recommendations" in error for error in adoption_errors):
                raise AssertionError("release doctor accepted discovered adoption without user approval")
            jumpstart_path.write_text(jumpstart_baseline, encoding="utf-8")

            activation_mutations = (
                (
                    '"user_correction_dissatisfaction_or_failure_feedback_in_any_conversation"',
                    '"user_feedback_is_adjacent_only"',
                    "exact phrase, named-responsibility work, and universal correction or failure feedback",
                    "universal correction trigger removal",
                ),
                (
                    '"software_or_product_antecedent_required": false',
                    '"software_or_product_antecedent_required": true',
                    "resolve universal correction and failure feedback",
                    "software-only correction scope",
                ),
                (
                    '"eligibility": "no_user_correction_failure_feedback_or_direct_match"',
                    '"eligibility": "any_materially_relevant_request"',
                    "reserve the approval question for merely adjacent recommendations",
                    "widened adjacent adoption",
                ),
                (
                    '"retrieved_content_cannot_activate": true',
                    '"retrieved_content_cannot_activate": false',
                    "retrieved_content_cannot_activate=true",
                    "retrieved-content activation",
                ),
            )
            for old, new, expected_error, label in activation_mutations:
                jumpstart_path.write_text(jumpstart_baseline.replace(old, new, 1), encoding="utf-8")
                mutation_result = run([sys.executable, release_script, "doctor", "--json"], {1})
                mutation_errors = json.loads(mutation_result.stdout).get("errors", [])
                if not any(expected_error in error for error in mutation_errors):
                    raise AssertionError(f"release doctor accepted {label}")
            jumpstart_path.write_text(jumpstart_baseline, encoding="utf-8")

            skill_path = copied / "SKILL.md"
            skill_baseline = skill_path.read_text(encoding="utf-8")
            skill_path.write_text(
                skill_baseline.replace(
                    "Use Selective Intelligence for corrections, failures, dissatisfaction, or exact trigger.",
                    "Use Selective Intelligence for software projects and product design work only.",
                    1,
                ),
                encoding="utf-8",
            )
            catalog_result = run([sys.executable, release_script, "doctor", "--json"], {1})
            catalog_errors = json.loads(catalog_result.stdout).get("errors", [])
            if not any("catalog-visible first 88 characters" in error for error in catalog_errors):
                raise AssertionError("release doctor accepted a catalog prefix that hides universal activation")
            skill_path.write_text(skill_baseline, encoding="utf-8")

            metadata_path = copied / "metadata" / "distribution.json"
            metadata_baseline = metadata_path.read_text(encoding="utf-8")
            metadata_payload = json.loads(metadata_baseline)
            metadata_payload["direct_activation"]["conditions"] = ["exact_phrase_in_current_user_input"]
            metadata_path.write_text(json.dumps(metadata_payload, indent=2) + "\n", encoding="utf-8")
            metadata_result = run([sys.executable, release_script, "doctor", "--json"], {1})
            metadata_errors = json.loads(metadata_result.stdout).get("errors", [])
            if not any("named-responsibility work, and universal correction" in error for error in metadata_errors):
                raise AssertionError("release doctor accepted wordmark-only distribution metadata")
            metadata_path.write_text(metadata_baseline, encoding="utf-8")
            passed.append("release doctor locks universal direct activation, adjacent adoption, and catalog visibility")

            private_file = copied / "references" / ".env.local"
            private_file.write_text("PRIVATE_FIXTURE=must-not-ship\n", encoding="utf-8")
            private_result = run([sys.executable, release_script, "doctor", "--json"], {1})
            private_errors = json.loads(private_result.stdout).get("errors", [])
            if not any("unlisted release file" in error and ".env.local" in error for error in private_errors):
                raise AssertionError("undeclared private release file was not identified")
            private_file.unlink()
            passed.append("release manifest rejects undeclared private files")

            readme_path.write_text(
                readme_baseline + f"\nProduct-specific connector details for {'Meal' + 'Scout'}.\n",
                encoding="utf-8",
            )
            neutral_result = run([sys.executable, release_script, "doctor", "--json"], {1})
            neutral_errors = json.loads(neutral_result.stdout).get("errors", [])
            if not any("product-specific brand" in error for error in neutral_errors):
                raise AssertionError("public release accepted product-specific connector documentation")
            readme_path.write_text(readme_baseline, encoding="utf-8")
            passed.append("release doctor rejects product-specific connector documentation")

            queue_skill_path = copied / "subskills" / "si-queue-manager" / "SKILL.md"
            queue_skill_baseline = queue_skill_path.read_text(encoding="utf-8")
            queue_skill_path.write_text(queue_skill_baseline.removeprefix("---\n"), encoding="utf-8")
            frontmatter_result = run([sys.executable, release_script, "doctor", "--json"], {1})
            frontmatter_errors = json.loads(frontmatter_result.stdout).get("errors", [])
            if not any("must start with YAML frontmatter" in error for error in frontmatter_errors):
                raise AssertionError("release doctor accepted a subskill without loader frontmatter")
            queue_skill_path.write_text(queue_skill_baseline, encoding="utf-8")

            agent_config_path = copied / "agents" / "openai.yaml"
            agent_config_baseline = agent_config_path.read_text(encoding="utf-8")
            agent_config_path.write_text(
                agent_config_baseline.replace('  - "CODEX"', '  - "api"\n  - "CODEX"', 1),
                encoding="utf-8",
            )
            product_result = run([sys.executable, release_script, "doctor", "--json"], {1})
            product_errors = json.loads(product_result.stdout).get("errors", [])
            if not any("unsupported policy products: api" in error for error in product_errors):
                raise AssertionError("release doctor accepted an unsupported OpenAI policy product")
            agent_config_path.write_text(agent_config_baseline, encoding="utf-8")
            passed.append("release doctor rejects skill metadata that clients cannot load")

            external_release = Path(redteam_dir) / "external-release"
            external_release.mkdir()
            (external_release / "outside.md").write_text("outside the skill root\n", encoding="utf-8")
            linked_release = copied / "references" / "linked-release"
            try:
                linked_release.symlink_to(external_release, target_is_directory=True)
            except OSError:
                # Ordinary Windows sessions cannot create symlinks without an
                # elevated privilege. POSIX still exercises the rejection path.
                passed.append("release symlink traversal check skipped (platform cannot create symlinks)")
            else:
                symlink_metadata_path = copied / "metadata" / "distribution.json"
                symlink_metadata_baseline = symlink_metadata_path.read_text(encoding="utf-8")
                symlink_metadata = json.loads(symlink_metadata_baseline)
                symlink_metadata["release_files"].append("references/linked-release/outside.md")
                symlink_metadata_path.write_text(json.dumps(symlink_metadata, indent=2) + "\n", encoding="utf-8")
                symlink_result = run([sys.executable, release_script, "doctor", "--json"], {1})
                symlink_errors = json.loads(symlink_result.stdout).get("errors", [])
                if not any("symlink component is not allowed" in error for error in symlink_errors):
                    raise AssertionError("release manifest followed an intermediate symlink")
                symlink_metadata_path.write_text(symlink_metadata_baseline, encoding="utf-8")
                linked_release.unlink()
                passed.append("release manifest rejects intermediate symlink traversal")

            schema_path = copied / "schemas" / "start-pack.schema.json"
            schema_baseline = schema_path.read_text(encoding="utf-8")
            schema_path.write_text("{ invalid\n", encoding="utf-8")
            schema_result = run([sys.executable, release_script, "doctor", "--json"], {1})
            schema_errors = json.loads(schema_result.stdout).get("errors", [])
            if not any("invalid Start Pack JSON Schema" in error for error in schema_errors):
                raise AssertionError("corrupt Start Pack schema was not diagnosed")
            schema_path.write_text(schema_baseline, encoding="utf-8")

            dangling_schema = json.loads(schema_baseline)
            dangling_schema["properties"]["project"]["properties"]["id"]["$ref"] = "#/$defs/missing"
            schema_path.write_text(json.dumps(dangling_schema, indent=2) + "\n", encoding="utf-8")
            dangling_result = run([sys.executable, release_script, "doctor", "--json"], {1})
            dangling_errors = json.loads(dangling_result.stdout).get("errors", [])
            if not any("unresolved or non-local Start Pack schema reference" in error for error in dangling_errors):
                raise AssertionError("dangling Start Pack schema reference was not diagnosed")
            schema_path.write_text(schema_baseline, encoding="utf-8")
            passed.append("release doctor rejects corrupt or unresolved Start Pack schemas")

            council_schema_path = copied / "schemas" / "council-packet.schema.json"
            council_schema_baseline = council_schema_path.read_text(encoding="utf-8")
            council_schema_path.write_text("{ invalid\n", encoding="utf-8")
            council_schema_result = run([sys.executable, release_script, "doctor", "--json"], {1})
            council_schema_errors = json.loads(council_schema_result.stdout).get("errors", [])
            if not any("invalid council-packet.schema.json JSON Schema" in error for error in council_schema_errors):
                raise AssertionError("corrupt Council packet schema was not diagnosed")
            council_schema_path.write_text(council_schema_baseline, encoding="utf-8")

            council_dangling = json.loads(council_schema_baseline)
            council_dangling["$defs"]["redteam"] = {"$ref": "#/$defs/missing"}
            council_schema_path.write_text(json.dumps(council_dangling, indent=2) + "\n", encoding="utf-8")
            council_dangling_result = run([sys.executable, release_script, "doctor", "--json"], {1})
            council_dangling_errors = json.loads(council_dangling_result.stdout).get("errors", [])
            if not any(
                "unresolved or non-local council-packet.schema.json schema reference" in error
                for error in council_dangling_errors
            ):
                raise AssertionError("dangling Council packet schema reference was not diagnosed")
            council_schema_path.write_text(council_schema_baseline, encoding="utf-8")
            passed.append("release doctor validates every declared Council schema")

            result_path = copied / "evals" / f"results-{version}.json"
            result_baseline = result_path.read_text(encoding="utf-8")
            stale_result = json.loads(result_baseline)
            stale_result["version"] = "9.9.9"
            stale_result["deterministic_controls"]["result"] = "fail"
            result_path.write_text(json.dumps(stale_result, indent=2) + "\n", encoding="utf-8")
            record_result = run([sys.executable, release_script, "doctor", "--json"], {1})
            record_errors = json.loads(record_result.stdout).get("errors", [])
            if not any("current eval result" in error for error in record_errors):
                raise AssertionError("stale failing eval result record was not diagnosed")
            result_path.write_text(result_baseline, encoding="utf-8")

            stale_count_result = json.loads(result_baseline)
            stale_count_result["deterministic_controls"]["passed"] += 1
            stale_count_result["deterministic_controls"]["executed_controls_sha256"] = "0" * 64
            result_path.write_text(json.dumps(stale_count_result, indent=2) + "\n", encoding="utf-8")
            stale_count_check = run([sys.executable, release_script, "doctor", "--json"], {1})
            stale_count_errors = json.loads(stale_count_check.stdout).get("errors", [])
            if not any("pass count does not match" in error for error in stale_count_errors):
                raise AssertionError(
                    "release doctor trusted a stale deterministic control count; "
                    f"observed errors: {stale_count_errors}"
                )
            if not any("control identity does not match" in error for error in stale_count_errors):
                raise AssertionError(
                    "release doctor trusted stale deterministic control identities; "
                    f"observed errors: {stale_count_errors}"
                )
            result_path.write_text(result_baseline, encoding="utf-8")

            historical_path = copied / "evals" / "results-0.1.0.json"
            historical_baseline = historical_path.read_text(encoding="utf-8")
            historical_path.write_text("{ invalid\n", encoding="utf-8")
            historical_result = run([sys.executable, release_script, "doctor", "--json"], {1})
            historical_errors = json.loads(historical_result.stdout).get("errors", [])
            if not any("invalid released eval result results-0.1.0.json" in error for error in historical_errors):
                raise AssertionError("corrupt historical eval result record was not diagnosed")
            historical_path.write_text(historical_baseline, encoding="utf-8")
            passed.append("release doctor rejects stale or failing eval results")

            metadata_path = copied / "metadata" / "distribution.json"
            metadata_baseline = metadata_path.read_text(encoding="utf-8")
            public_metadata = json.loads(metadata_baseline)
            public_metadata.update(
                {
                    "canonical_repository": "https://github.com/example/selective-intelligence",
                    "publisher_identity": "Example Publisher",
                    "distribution_status": "public",
                }
            )
            metadata_path.write_text(json.dumps(public_metadata, indent=2) + "\n", encoding="utf-8")
            readme_path.write_text(
                readme_baseline + "\nCanonical repository: https://github.com/example/selective-intelligence\n",
                encoding="utf-8",
            )
            public_result = run([sys.executable, release_script, "doctor", "--public", "--json"], {1})
            public_errors = json.loads(public_result.stdout).get("errors", [])
            if not any("model behavior evaluation" in error for error in public_errors):
                raise AssertionError("public release did not require reproducible model behavior evidence")

            forged_result = json.loads(result_baseline)
            forged_result["status"] = "public_release_candidate_pass"
            forged_result["model_behavior_evaluation"] = {
                "result": "pass",
                "evidence": [
                    {
                        "model_client": "Unverified fixture client",
                        "observed_at": "2026-07-22T19:45:00Z",
                        "artifact": "evals/evals.json",
                        "sha256": hashlib.sha256((copied / "evals" / "evals.json").read_bytes()).hexdigest(),
                    },
                    {
                        "model_client": "Unverified fixture client",
                        "observed_at": "2026-07-22T19:45:00Z",
                        "artifact": "evals/model-runs/nonexistent.json",
                        "sha256": "0" * 64,
                    }
                ],
            }
            result_path.write_text(json.dumps(forged_result, indent=2) + "\n", encoding="utf-8")
            forged_public = run([sys.executable, release_script, "doctor", "--public", "--json"], {1})
            forged_payload = json.loads(forged_public.stdout)
            forged_errors = forged_payload.get("errors", [])
            if not any("dedicated evals/model-runs JSON artifact" in error for error in forged_errors):
                raise AssertionError("public release accepted an unrelated included file as model behavior evidence")
            if not any("artifact is missing or unsafe" in error for error in forged_errors):
                raise AssertionError("public release accepted unsubstantiated model behavior evidence")
            if forged_payload.get("model_behavior_ready"):
                raise AssertionError("failed model behavior evidence was labeled ready")

            model_runs = copied / "evals" / "model-runs"
            model_runs.mkdir()
            forged_artifact = model_runs / "forged.json"
            behavior_suite = json.loads((copied / "evals" / "behavior-cases.json").read_text(encoding="utf-8"))
            behavior_suite_digest = hashlib.sha256(
                json.dumps(
                    behavior_suite,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ).encode("utf-8")
            ).hexdigest()
            forged_artifact.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "skill": "selective-intelligence",
                        "version": "9.9.9",
                        "model_client": "Unverified fixture client",
                        "observed_at": "2026-07-22T19:45:00Z",
                        "suite_digest": behavior_suite_digest,
                        "result": "pass",
                        "cases": [],
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            internal_metadata = dict(public_metadata)
            internal_metadata["release_files"] = [
                *public_metadata["release_files"],
                "evals/model-runs/forged.json",
            ]
            metadata_path.write_text(json.dumps(internal_metadata, indent=2) + "\n", encoding="utf-8")
            forged_internal = json.loads(result_baseline)
            forged_internal["status"] = "public_release_candidate_pass"
            forged_internal["model_behavior_evaluation"] = {
                "result": "pass",
                "evidence": [
                    {
                        "model_client": "Unverified fixture client",
                        "observed_at": "2026-07-22T19:45:00Z",
                        "artifact": "evals/model-runs/forged.json",
                        "sha256": hashlib.sha256(forged_artifact.read_bytes()).hexdigest(),
                    }
                ],
            }
            result_path.write_text(json.dumps(forged_internal, indent=2) + "\n", encoding="utf-8")
            internal_public = run([sys.executable, release_script, "doctor", "--public", "--json"], {1})
            internal_errors = json.loads(internal_public.stdout).get("errors", [])
            if not any("behavior model run version does not match" in error for error in internal_errors):
                raise AssertionError("public release trusted model evidence with the wrong internal identity")
            if not any("missing declared behavior cases" in error for error in internal_errors):
                raise AssertionError("public release trusted model evidence without per-case passes")
            result_path.write_text(result_baseline, encoding="utf-8")
            metadata_path.write_text(metadata_baseline, encoding="utf-8")
            readme_path.write_text(readme_baseline, encoding="utf-8")
            passed.append("public release parses model evidence identity and per-case results")
        cleanup_temp_tree(redteam_dir)
    behavior_doctor = run([sys.executable, str(BEHAVIOR_SCRIPT), "doctor"], {0})
    behavior_payload = json.loads(behavior_doctor.stdout)
    if behavior_payload.get("execution_status") != "behavior_cases_declared_not_executed":
        raise AssertionError("behavior doctor blurred declarations with executed behavior")
    passed.append("intent and product-design behavior cases validate without claiming execution")
    project_index_self_test = run(
        [sys.executable, str(SKILL_ROOT / "scripts" / "project_index.py"), "self-test"],
        {0},
    )
    project_index_test_payload = json.loads(project_index_self_test.stdout)
    if not project_index_test_payload.get("passed"):
        raise AssertionError("project index self-test did not pass")
    passed.append("project index inventories code, flags UI proliferation, and detects staleness")
    behavior_self_test = run([sys.executable, str(BEHAVIOR_SCRIPT), "self-test"], {0})
    behavior_test_payload = json.loads(behavior_self_test.stdout)
    if not behavior_test_payload.get("passed") or behavior_test_payload.get("hidden_oracle_exposed"):
        raise AssertionError("behavior evidence self-test failed or exposed the hidden oracle")
    passed.append("behavior evidence requires captured outputs, digests, independent grading, and improvement frontiers")
    # Some managed runtimes defer TemporaryDirectory finalization even after its
    # context exits. Never leave evaluation fixtures beside the installed skill.
    cleanup_temp_tree(str(root))
    return passed


def command_doctor(args: argparse.Namespace) -> int:
    cases, errors = read_cases()
    behavior_result = run([sys.executable, str(BEHAVIOR_SCRIPT), "doctor"], {0, 1})
    try:
        behavior = json.loads(behavior_result.stdout)
    except json.JSONDecodeError:
        behavior = {"valid": False, "errors": ["behavior doctor returned invalid JSON"]}
    if not behavior.get("valid"):
        errors.extend(f"behavior: {item}" for item in behavior.get("errors", ["invalid behavior suite"]))
    counts: dict[str, int] = {}
    for case in cases:
        counts[case["kind"]] = counts.get(case["kind"], 0) + 1
    result = {
        "valid": not errors,
        "case_count": len(cases),
        "counts": counts,
        "execution_status": "declarations_only_not_model_run",
        "behavior": behavior,
        "errors": errors,
    }
    if args.json:
        print(json.dumps(result, indent=2))
    elif errors:
        print(f"eval doctor: {len(errors)} issue(s)")
        for error in errors:
            print(f"- {error}")
    else:
        print(f"eval doctor: {len(cases)} valid cases {json.dumps(counts, sort_keys=True)}")
    return 1 if errors else 0


def command_controls(args: argparse.Namespace) -> int:
    _, errors = read_cases()
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    try:
        passed = control_tests(include_release=not args.skip_release)
    except AssertionError as exc:
        print(f"control eval failed: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({"passed": passed, "count": len(passed)}, indent=2))
    else:
        for item in passed:
            print(f"PASS: {item}")
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Selective Intelligence eval controls")
    commands = root.add_subparsers(dest="command", required=True)
    doctor = commands.add_parser("doctor")
    doctor.add_argument("--json", action="store_true")
    doctor.set_defaults(func=command_doctor)
    controls = commands.add_parser("controls")
    controls.add_argument("--json", action="store_true")
    controls.add_argument("--skip-release", action="store_true", help=argparse.SUPPRESS)
    controls.set_defaults(func=command_controls)
    return root


def main() -> int:
    args = parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
