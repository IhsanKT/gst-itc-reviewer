"""Validates every raw LLM response in code: JSON, Pydantic schema, line coverage, and citation IDs.

A run that fails any check is kept as an invalid run with its error. It is never silently dropped, and it
never produces a label on its own: an invalid run routes the line to the CA.
"""
from __future__ import annotations

import json

from pydantic import ValidationError

from itc.rulepack import BlockedCreditPack, is_valid_citation
from itc.schemas import LLMBatchOutput


def validate_batch(raw: str | None, expected_line_ids: list[str], pack: BlockedCreditPack,
                   call_error: str | None = None) -> tuple[dict[str, dict], list[str]]:
    """Returns ({line_id: run}, batch_errors). Each run: {rule_id, reason, valid, error}."""
    def all_invalid(msg: str):
        return {lid: {"rule_id": None, "reason": "", "valid": False, "error": msg} for lid in expected_line_ids}, [msg]

    if call_error:
        return all_invalid(f"LLM call failed: {call_error}")
    try:
        parsed = LLMBatchOutput.model_validate(json.loads(raw or ""))
    except json.JSONDecodeError as e:
        return all_invalid(f"response is not JSON: {e.msg}")
    except ValidationError as e:
        return all_invalid(f"response does not match schema: {e.error_count()} error(s)")

    runs: dict[str, dict] = {}
    errors: list[str] = []
    for item in parsed.lines:
        if item.line_id not in expected_line_ids:
            errors.append(f"unexpected line_id {item.line_id!r} in response")
            continue
        if item.line_id in runs:
            errors.append(f"duplicate line_id {item.line_id!r} in response")
            runs[item.line_id] = {"rule_id": None, "reason": "", "valid": False, "error": "duplicate answer"}
            continue
        if not is_valid_citation(item.rule_id, pack):
            msg = f"citation {item.rule_id!r} is not in rule pack {pack.version}"
            errors.append(f"{item.line_id}: {msg}")
            runs[item.line_id] = {"rule_id": item.rule_id, "reason": item.reason, "valid": False, "error": msg}
            continue
        runs[item.line_id] = {"rule_id": item.rule_id, "reason": item.reason, "valid": True, "error": None}
    for lid in expected_line_ids:
        if lid not in runs:
            errors.append(f"{lid}: missing from response")
            runs[lid] = {"rule_id": None, "reason": "", "valid": False, "error": "missing from response"}
    return runs, errors
