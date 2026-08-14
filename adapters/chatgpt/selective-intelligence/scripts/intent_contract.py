#!/usr/bin/env python3
"""Intent locking and reconciliation for Selective Intelligence.

This module is deliberately provider-neutral. It can accept a richer structured
classification from any reasoning adapter, but it always preserves the raw user
text and applies conservative deterministic extraction first. The deterministic
path never invents facts or silently weakens explicit constraints.

Step-1 intent control: corrections are first-class operations
(ADD | MODIFY | REPLACE | RETRACT | SUPERSEDE | ROLLBACK), not additive
refinements. Repudiations such as "I didn't say halt" retract an invented
interpretation; they must not be unioned into product intent.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any

_INTENT_SCHEMA = "si.intent_contract.v2"

INTENT_OPERATIONS = (
    "ADD",
    "MODIFY",
    "REPLACE",
    "RETRACT",
    "SUPERSEDE",
    "ROLLBACK",
)

# Process / invented-control terms that agents commonly invent without authority.
_PROCESS_TERMS = (
    "halt",
    "freeze",
    "resume",
    "pause",
    "stop",
    "restart",
    "abort",
    "cancel",
    "suspend",
    "kill",
    "block",
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _event_id() -> str:
    return f"intent-{uuid.uuid4().hex[:12]}"


def _clauses(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|[\r\n]+|\s*;\s*", text.strip())
    return [p.strip(" \t-•") for p in parts if p.strip(" \t-•")]


def _norm(text: str) -> str:
    text = re.sub(r"[^a-z0-9]+", " ", text.lower())
    return " ".join(text.split())


def _expand_contractions(text: str) -> str:
    """Normalize informal negation so keyword parsers cannot miss repudiations."""
    out = text.lower()
    replacements = (
        (r"\bdidnt\b", "did not"),
        (r"\bdidn't\b", "did not"),
        (r"\bdont\b", "do not"),
        (r"\bdon't\b", "do not"),
        (r"\bwont\b", "will not"),
        (r"\bwon't\b", "will not"),
        (r"\bcant\b", "cannot"),
        (r"\bcan't\b", "cannot"),
        (r"\bisnt\b", "is not"),
        (r"\bisn't\b", "is not"),
        (r"\barent\b", "are not"),
        (r"\baren't\b", "are not"),
        (r"\bwasnt\b", "was not"),
        (r"\bwasn't\b", "was not"),
        (r"\bwerent\b", "were not"),
        (r"\bweren't\b", "were not"),
        (r"\bhaven't\b", "have not"),
        (r"\bhavent\b", "have not"),
        (r"\bhasn't\b", "has not"),
        (r"\bhasnt\b", "has not"),
        (r"\bnever\s+said\b", "did not say"),
        (r"\bnever\s+told\b", "did not tell"),
        (r"\bnever\s+asked\b", "did not ask"),
    )
    for pattern, repl in replacements:
        out = re.sub(pattern, repl, out)
    return out


def _dedupe(items: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        key = _norm(item)
        if key and key not in seen:
            seen.add(key)
            out.append(item.strip())
    return out


def intent_hash(payload: dict[str, Any]) -> str:
    """Stable hash over the authoritative intent fields of a contract or checkpoint."""
    material = {
        "product_intent": payload.get("product_intent") or payload.get("intent_summary") or "",
        "process_directives": payload.get("process_directives") or payload.get("planned_next_actions") or [],
        "constraints": payload.get("constraints") or [],
        "prohibitions": payload.get("prohibitions") or [],
        "acceptance_criteria": payload.get("acceptance_criteria") or [],
        "required_concepts": payload.get("required_concepts") or [],
        "superseded_concepts": payload.get("superseded_concepts") or [],
        "scope": payload.get("scope") or [],
        "non_goals": payload.get("non_goals") or [],
        "operation": payload.get("operation"),
        "operation_targets": payload.get("operation_targets") or [],
    }
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _extract_prohibited_concepts(clause: str) -> list[str]:
    lowered = _expand_contractions(clause)
    patterns = [
        r"(?:do not|must not|never)\s+(.+)",
        r"\bno\s+(.+)",
        r"(?:rather than|instead of)\s+(.+)",
    ]
    concepts: list[str] = []
    for pattern in patterns:
        match = re.search(pattern, lowered)
        if match:
            value = match.group(1).strip(" .,:;")
            value = re.split(r"\b(?:and|or|but)\b", value, maxsplit=1)[0].strip()
            if value:
                concepts.append(value)
    return concepts


def _extract_required_concepts(clause: str) -> list[str]:
    lowered = _expand_contractions(clause)
    concepts: list[str] = []
    for pattern in (
        r"(?:must|should|needs? to|required to)\s+(.+)",
        r"(?:only)\s+(.+)",
        r"(?:rather than|instead of)\s+.+?[,;]?\s*(?:use|show|display|implement)\s+(.+)",
    ):
        match = re.search(pattern, lowered)
        if match:
            value = match.group(1).strip(" .,:;")
            if value:
                concepts.append(value)
    return concepts


def _extract_retracted_targets(text: str) -> list[str]:
    """Pull the concepts the user is repudiating from correction language."""
    lowered = _expand_contractions(text)
    targets: list[str] = []
    patterns = (
        r"(?:did not|do not)\s+(?:say|tell|ask|request|want|mean)\s+(?:to\s+)?(.+?)(?:\s+did\s+i|\s*\?|$|,|\.|!)",
        r"(?:that|this)\s+(?:was|is)\s+never\s+(?:said|given|requested|an?\s+instruction)\b",
        r"(?:remove|drop|retract|without)\s+(?:the\s+)?(.+?)(?:\s+directive|\s+instruction|$|,|\.|!)",
        r"(?:not|never)\s+(?:a\s+)?(?:halt|freeze|pause|stop|resume|restart)\b",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, lowered):
            if match.lastindex:
                value = match.group(1).strip(" .,:;?!'\"")
                value = re.split(r"\b(?:did i|or|and|but|right)\b", value, maxsplit=1)[0].strip()
                if value:
                    targets.append(value)
            else:
                # Bare process-term repudiation like "not a halt"
                for term in _PROCESS_TERMS:
                    if term in match.group(0):
                        targets.append(term)
    # Direct mention of process terms in a repudiation utterance.
    if _is_repudiation_utterance(lowered):
        for term in _PROCESS_TERMS:
            if re.search(rf"\b{re.escape(term)}\b", lowered):
                targets.append(term)
    return _dedupe(targets)


def _is_standalone_negation(text: str) -> bool:
    lowered = _expand_contractions(text).strip()
    return bool(
        re.fullmatch(
            r"(?:no|nope|nah|wrong|incorrect|false|n|no\s+way|absolutely\s+not)[.!?]*",
            lowered,
        )
    )


def _is_repudiation_utterance(text: str) -> bool:
    lowered = _expand_contractions(text)
    if _is_standalone_negation(lowered):
        return True
    patterns = (
        r"\bdid not\s+(?:say|tell|ask|request|want|mean)\b",
        r"\bi\s+never\s+(?:said|told|asked|requested|wanted)\b",
        r"\bthat\s+(?:was|is)\s+never\s+(?:said|given|requested|an?\s+instruction)\b",
        r"\bnever\s+(?:said|told|asked|gave)\b",
        r"\byou\s+(?:invented|made\s+up|assumed)\b",
        r"\bi\s+did\s+not\s+(?:say|tell|ask)\b",
        r"\bkeep\s+working\b",
        r"\bdo\s+not\s+(?:halt|freeze|pause|stop|add)\b",
        r"\bcriticism\s+(?:is\s+)?not\s+(?:a\s+)?(?:new\s+)?(?:task|instruction)\b",
        r"\bstop\s+adding\s+things\b",
        r"\bdo\s+only\s+(?:the\s+)?original\b",
        r"\bnope\b",
    )
    return any(re.search(p, lowered) for p in patterns)


def _text_derived_operation(raw_text: str, *, event_type: str) -> tuple[str, list[str]] | None:
    """Classify operation from raw user text alone (no model override)."""
    lowered = _expand_contractions(raw_text)
    if event_type == "correction" or _is_repudiation_utterance(lowered):
        if re.search(r"\brollback\b|\brevert\s+to\b|\bundo\s+(?:the\s+)?last\b", lowered):
            return "ROLLBACK", _extract_retracted_targets(raw_text)
        if re.search(r"\breplace\s+(?:the\s+)?(?:prior|previous|whole)\s+scope\b|\breplace\s+prior\b", lowered):
            return "REPLACE", _extract_retracted_targets(raw_text)
        if re.search(r"\bsupersede\b|\binstead\s*,?\s+do\b|\bnew\s+scope\s+is\b", lowered):
            return "SUPERSEDE", _extract_retracted_targets(raw_text)
        if _is_repudiation_utterance(lowered):
            return "RETRACT", _extract_retracted_targets(raw_text)
        if re.search(r"\bmodify\b|\bchange\b|\bupdate\b|\brefine\b", lowered):
            return "MODIFY", []
        return "MODIFY", []
    if re.search(r"\breplace\b", lowered):
        return "REPLACE", []
    return None


def _detect_operation(
    raw_text: str,
    *,
    event_type: str,
    structured_override: dict[str, Any] | None,
) -> tuple[str, list[str]]:
    # Text-derived repudiation / RETRACT must survive a conflicting model override.
    text_derived = _text_derived_operation(raw_text, event_type=event_type)

    if structured_override and structured_override.get("operation"):
        op = str(structured_override["operation"]).upper()
        if op not in INTENT_OPERATIONS:
            raise ValueError(f"unsupported intent operation: {op}")
        targets = list(structured_override.get("operation_targets") or [])
        if not all(isinstance(t, str) for t in targets):
            raise ValueError("operation_targets override must be a list of strings")
        if text_derived and text_derived[0] == "RETRACT" and op != "RETRACT":
            return text_derived
        return op, targets

    if text_derived:
        return text_derived
    return "ADD", []


def validate_override(override: dict[str, Any]) -> None:
    allowed = {
        "product_intent",
        "process_directives",
        "constraints",
        "prohibitions",
        "acceptance_criteria",
        "assumptions",
        "unknowns",
        "contradictions",
        "required_concepts",
        "superseded_concepts",
        "operation",
        "operation_targets",
        "scope",
        "non_goals",
    }
    unknown = sorted(set(override) - allowed)
    if unknown:
        raise ValueError(f"unsupported intent override fields: {', '.join(unknown)}")
    for key, value in override.items():
        if key == "product_intent":
            if not isinstance(value, str):
                raise ValueError("product_intent override must be a string")
        elif key == "operation":
            if not isinstance(value, str) or value.upper() not in INTENT_OPERATIONS:
                raise ValueError(f"operation override must be one of {', '.join(INTENT_OPERATIONS)}")
        elif not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise ValueError(f"{key} override must be a list of strings")


def classify_intent(
    raw_text: str,
    *,
    event_type: str = "request",
    structured_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify an instruction without discarding the source text.

    A reasoning adapter may supply ``structured_override``. Explicit text-derived
    prohibitions and repudiation operations are always retained even when an
    override is supplied. ``structured_override`` is never the only path to
    correct repudiation handling.
    """
    raw_text = (raw_text or "").strip()
    if not raw_text:
        raise ValueError("intent text is empty")

    operation, operation_targets = _detect_operation(
        raw_text, event_type=event_type, structured_override=structured_override
    )
    clauses = _clauses(raw_text)
    prohibitions: list[str] = []
    constraints: list[str] = []
    process: list[str] = []
    acceptance: list[str] = []
    product: list[str] = []
    required: list[str] = []
    superseded: list[str] = []

    is_retract_like = operation in {"RETRACT", "ROLLBACK", "SUPERSEDE"}

    for clause in clauses:
        low = _expand_contractions(clause)
        is_prohibition = bool(re.search(r"\b(do not|must not|never|no)\b", low)) and not _is_standalone_negation(low)
        is_process = bool(
            re.search(
                r"\b(first|before|inspect|discover|verify|validate|report|preserve|continue|stop|resume|halt|freeze)\b",
                low,
            )
        )
        is_acceptance = bool(re.search(r"\b(must|should|only|required|acceptance|complete|verified)\b", low))
        is_product = bool(
            re.search(r"\b(add|build|create|implement|fix|repair|update|change|make|turn|produce|design)\b", low)
        )

        if is_retract_like:
            # Repudiations are not product asks and are not additive process directives.
            if is_prohibition and not _is_repudiation_utterance(low):
                prohibitions.append(clause)
                constraints.append(clause)
                superseded.extend(_extract_prohibited_concepts(clause))
            continue

        if is_prohibition:
            prohibitions.append(clause)
            constraints.append(clause)
            superseded.extend(_extract_prohibited_concepts(clause))
        if is_process:
            process.append(clause)
        if is_acceptance:
            acceptance.append(clause)
            required.extend(_extract_required_concepts(clause))
        if is_product and not is_prohibition:
            product.append(clause)

    if is_retract_like:
        product_intent = ""
        if operation_targets:
            superseded = _dedupe(superseded + operation_targets)
    else:
        if not product:
            product = [clauses[0]]
        product_intent = " ".join(_dedupe(product))

    result: dict[str, Any] = {
        "schemaVersion": _INTENT_SCHEMA,
        "eventId": _event_id(),
        "eventType": event_type,
        "timestamp": _now(),
        "rawText": raw_text,
        "operation": operation,
        "operation_targets": _dedupe(operation_targets),
        "product_intent": product_intent,
        "process_directives": [] if is_retract_like else _dedupe(process),
        "constraints": _dedupe(constraints),
        "prohibitions": _dedupe(prohibitions),
        "acceptance_criteria": [] if is_retract_like else _dedupe(acceptance),
        "assumptions": [],
        "unknowns": [],
        "contradictions": [],
        "required_concepts": [] if is_retract_like else _dedupe(required),
        "superseded_concepts": _dedupe(superseded + (operation_targets if is_retract_like else [])),
        "scope": [],
        "non_goals": list(operation_targets) if is_retract_like else [],
        "source": "deterministic_explicit_text",
    }
    result["intent_hash"] = intent_hash(result)

    if structured_override:
        validate_override(structured_override)
        for key, value in structured_override.items():
            if key in {"operation", "operation_targets"}:
                continue
            if key == "product_intent":
                if value.strip() and not is_retract_like:
                    result[key] = value.strip()
            else:
                result[key] = _dedupe(result.get(key, []) + value)
        result["source"] = "deterministic_text_plus_validated_reasoning_adapter"
        result["intent_hash"] = intent_hash(result)

    return result


def _remove_matching(items: list[str], targets: list[str]) -> tuple[list[str], list[str]]:
    """Remove items whose normalized text overlaps a retract target."""
    target_tokens = concept_tokens(targets)
    retained: list[str] = []
    removed: list[str] = []
    for item in items:
        item_tokens = concept_tokens([item])
        item_norm = _norm(item)
        hit = bool(target_tokens & item_tokens) or any(_norm(t) and _norm(t) in item_norm for t in targets)
        if hit:
            removed.append(item)
        else:
            retained.append(item)
    return retained, removed


def merge_active_contract(active: dict[str, Any] | None, event: dict[str, Any]) -> dict[str, Any]:
    """Merge a request/correction using the event's intent operation.

    RETRACT / ROLLBACK remove repudiated interpretations. They are never unioned
    into ``refinements`` as if they were additive product asks.
    """
    operation = str(event.get("operation") or "ADD").upper()
    if operation not in INTENT_OPERATIONS:
        raise ValueError(f"unsupported intent operation: {operation}")

    active = dict(active or {})
    if not active:
        return {
            "schemaVersion": _INTENT_SCHEMA,
            "product_intent": event.get("product_intent") or "",
            "process_directives": list(event.get("process_directives") or []),
            "constraints": list(event.get("constraints") or []),
            "prohibitions": list(event.get("prohibitions") or []),
            "acceptance_criteria": list(event.get("acceptance_criteria") or []),
            "assumptions": list(event.get("assumptions") or []),
            "unknowns": list(event.get("unknowns") or []),
            "contradictions": list(event.get("contradictions") or []),
            "required_concepts": list(event.get("required_concepts") or []),
            "superseded_concepts": list(event.get("superseded_concepts") or []),
            "scope": list(event.get("scope") or []),
            "non_goals": list(event.get("non_goals") or []),
            "operationHistory": [
                {
                    "operation": operation,
                    "eventId": event["eventId"],
                    "targets": list(event.get("operation_targets") or []),
                }
            ],
            "sourceEventIds": [event["eventId"]],
            "updatedAt": _now(),
            "intent_hash": intent_hash(event),
        }

    diff: dict[str, Any] = {
        "operation": operation,
        "removed": {},
        "retained": {},
        "changed": {},
        "eventId": event["eventId"],
    }
    targets = list(event.get("operation_targets") or event.get("superseded_concepts") or [])

    if operation in {"RETRACT", "ROLLBACK"}:
        for key in (
            "process_directives",
            "constraints",
            "prohibitions",
            "acceptance_criteria",
            "assumptions",
            "required_concepts",
            "scope",
        ):
            retained, removed = _remove_matching(list(active.get(key, [])), targets)
            if removed:
                diff["removed"][key] = removed
                diff["retained"][key] = retained
                active[key] = retained
        # Do not treat the repudiation text as a new product_intent or refinement.
        active["superseded_concepts"] = _dedupe(
            list(active.get("superseded_concepts", [])) + targets + list(event.get("superseded_concepts") or [])
        )
        active["non_goals"] = _dedupe(list(active.get("non_goals", [])) + targets)
        if event.get("prohibitions"):
            active["prohibitions"] = _dedupe(list(active.get("prohibitions", [])) + list(event["prohibitions"]))
            active["constraints"] = _dedupe(list(active.get("constraints", [])) + list(event["constraints"]))
        # Explicitly record that this was not an additive refinement.
        active.setdefault("retractedInterpretations", []).append(
            {
                "eventId": event["eventId"],
                "rawText": event.get("rawText"),
                "targets": targets,
                "timestamp": _now(),
            }
        )

    elif operation == "REPLACE":
        if event.get("product_intent"):
            diff["changed"]["product_intent"] = {
                "from": active.get("product_intent"),
                "to": event["product_intent"],
            }
            active["product_intent"] = event["product_intent"]
        for key in (
            "process_directives",
            "constraints",
            "prohibitions",
            "acceptance_criteria",
            "assumptions",
            "unknowns",
            "contradictions",
            "required_concepts",
            "scope",
            "non_goals",
        ):
            if event.get(key):
                diff["changed"][key] = {"from": list(active.get(key, [])), "to": list(event[key])}
                active[key] = list(event[key])
        active["superseded_concepts"] = _dedupe(
            list(active.get("superseded_concepts", [])) + list(event.get("superseded_concepts") or []) + targets
        )

    elif operation == "SUPERSEDE":
        if event.get("product_intent"):
            diff["changed"]["product_intent"] = {
                "from": active.get("product_intent"),
                "to": event["product_intent"],
            }
            active["product_intent"] = event["product_intent"]
        for key in (
            "process_directives",
            "constraints",
            "prohibitions",
            "acceptance_criteria",
            "assumptions",
            "unknowns",
            "contradictions",
            "required_concepts",
            "scope",
            "non_goals",
        ):
            if event.get(key) is not None:
                active[key] = _dedupe(list(event.get(key) or []))
        active["superseded_concepts"] = _dedupe(
            list(active.get("superseded_concepts", [])) + list(event.get("superseded_concepts") or []) + targets
        )

    elif operation == "MODIFY":
        if event.get("product_intent"):
            active.setdefault("refinements", []).append(event["product_intent"])
            diff["changed"]["refinements"] = list(active.get("refinements", []))
        for key in (
            "process_directives",
            "constraints",
            "prohibitions",
            "acceptance_criteria",
            "assumptions",
            "unknowns",
            "contradictions",
            "required_concepts",
            "superseded_concepts",
            "scope",
            "non_goals",
        ):
            active[key] = _dedupe(list(active.get(key, [])) + list(event.get(key, [])))

    else:  # ADD
        if event.get("product_intent"):
            if active.get("product_intent"):
                active.setdefault("refinements", []).append(event["product_intent"])
            else:
                active["product_intent"] = event["product_intent"]
        for key in (
            "process_directives",
            "constraints",
            "prohibitions",
            "acceptance_criteria",
            "assumptions",
            "unknowns",
            "contradictions",
            "required_concepts",
            "superseded_concepts",
            "scope",
            "non_goals",
        ):
            active[key] = _dedupe(list(active.get(key, [])) + list(event.get(key, [])))

    active.setdefault("operationHistory", []).append(
        {
            "operation": operation,
            "eventId": event["eventId"],
            "targets": targets,
            "diff": diff,
        }
    )
    active.setdefault("sourceEventIds", []).append(event["eventId"])
    active["updatedAt"] = _now()
    active["lastOperation"] = operation
    active["lastOperationDiff"] = diff
    active["intent_hash"] = intent_hash(active)
    return active


def concept_tokens(values: list[str]) -> set[str]:
    stop = {
        "the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "with",
        "must", "should", "do", "not", "only", "it", "this", "that", "be", "is",
        "did", "say", "tell", "ask", "i", "you", "we", "they", "nope", "no",
    }
    tokens: set[str] = set()
    for value in values:
        tokens.update(t for t in _norm(value).split() if len(t) > 2 and t not in stop)
    return tokens
