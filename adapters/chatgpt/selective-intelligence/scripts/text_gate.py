#!/usr/bin/env python3
"""Text-gate responses for non-Platynum SI clients (Cursor, Claude, IDE agents).

Platynum owns clickable Approve/Correct. Outside Platynum, do NOT render decorative
👍/👎 or fake Approve/Correct controls. Clients must reply with an explicit text gate:

  APPROVE
  CORRECT: <instruction>

Both map to the same SI transactions as Platynum buttons (approve / interrupt).
Execution stays locked until a valid gate response is applied.
"""
from __future__ import annotations

import re
from typing import Any

GATE_APPROVE = "APPROVE"
GATE_CORRECT = "CORRECT"

_APPROVE_RE = re.compile(r"^\s*APPROVE\s*$", re.IGNORECASE)
_CORRECT_RE = re.compile(r"^\s*CORRECT\s*:\s*(.+)\s*$", re.IGNORECASE | re.DOTALL)


class TextGateError(ValueError):
    """Invalid or missing text-gate response."""


def parse_text_gate(raw: str) -> dict[str, Any]:
    """Parse a user/agent text-gate reply into an SI action.

    Returns:
      {"action": "approve"} or {"action": "correct", "correction": "..."}.
    Raises TextGateError when the reply is not a valid gate response.
    """
    text = (raw or "").strip()
    if not text:
        raise TextGateError(
            "execution locked: reply with APPROVE or CORRECT: <instruction>"
        )
    if _APPROVE_RE.match(text):
        return {"action": "approve", "raw": text}
    match = _CORRECT_RE.match(text)
    if match:
        correction = match.group(1).strip()
        if not correction:
            raise TextGateError("CORRECT requires an instruction after the colon")
        return {"action": "correct", "correction": correction, "raw": text}
    raise TextGateError(
        "invalid text gate; reply with exactly APPROVE or CORRECT: <instruction>"
    )


def text_gate_prompt(*, checkpoint_summary: str | None = None) -> str:
    """Plain-language prompt for IDE/agent surfaces (no decorative controls)."""
    lines = [
        "SI checkpoint — execution is locked until you reply with a text gate.",
        "Do not render decorative Approve/Correct controls as if they were clickable.",
        "Reply with exactly one of:",
        "  APPROVE",
        "  CORRECT: <your instruction>",
    ]
    if checkpoint_summary and checkpoint_summary.strip():
        lines.insert(1, f"What SI understands: {checkpoint_summary.strip()}")
    return "\n".join(lines)
