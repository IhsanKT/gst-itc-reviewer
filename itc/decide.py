"""Deterministic label composition and routing. No LLM here: these are the rules a CA can audit.

Label precedence is Blocked > Deferred > Eligible.
- Blocked: a 17(5) clause applies with no exception, or the claim is time-barred under s.16(4).
- Deferred: a s.16 condition is not met yet (2B, receipt, 180-day payment, invoice fields).
- Eligible: none of the above.
The primary rule ID is the one that decided the label; all applicable IDs are cited.
"""
from __future__ import annotations

from collections import Counter

from itc.rulepack import NONE_ID, BlockedCreditPack

S16_ORDER = ["S16_2_A", "S16_2_AA", "S16_2_B", "S16_2_PROVISO_180"]


def label_from_17_5(rule_id: str | None, pack: BlockedCreditPack) -> str:
    """Clause -> Blocked; exception or NONE -> Eligible; unknown (no valid answer) -> Blocked (conservative)."""
    if rule_id is None:
        return "Blocked"
    clause, exception = pack.resolve(rule_id)
    return "Blocked" if clause is not None and exception is None else "Eligible"


def compose_label(s16_checks: list[dict], rule_id: str | None, pack: BlockedCreditPack) -> dict:
    failed = [c for c in s16_checks if not c["passed"]]
    blocked_16 = [c["rule_id"] for c in failed if c["outcome_on_fail"] == "Blocked"]
    deferred_16 = sorted((c["rule_id"] for c in failed if c["outcome_on_fail"] == "Deferred"),
                         key=lambda r: S16_ORDER.index(r) if r in S16_ORDER else len(S16_ORDER))
    label_17 = label_from_17_5(rule_id, pack)
    cited = blocked_16 + deferred_16 + ([rule_id] if rule_id not in (None, NONE_ID) else [])

    if blocked_16:
        label, primary = "Blocked", blocked_16[0]
    elif label_17 == "Blocked":
        label, primary = "Blocked", rule_id  # None when no valid classifier answer
    elif deferred_16:
        label, primary = "Deferred", deferred_16[0]
    else:
        label, primary = "Eligible", rule_id
    return {"label": label, "primary_rule_id": primary, "cited_rule_ids": cited}


def agreement(runs: list[dict], runs_expected: int) -> dict:
    """Majority over valid runs. On a tie the most conservative candidate (a blocking clause) wins."""
    valid = [r["rule_id"] for r in runs if r["valid"]]
    counts = Counter(valid)
    if not counts:
        return {"rule_id": None, "agree": 0, "of": runs_expected, "unanimous": False, "candidates": {}}
    top = max(counts.values())
    tied = sorted(rid for rid, n in counts.items() if n == top)
    blocking = [rid for rid in tied if rid != NONE_ID and "." not in rid]
    choice = blocking[0] if blocking else tied[0]
    unanimous = len(counts) == 1 and len(valid) == runs_expected
    return {"rule_id": choice, "agree": top, "of": runs_expected, "unanimous": unanimous, "candidates": dict(counts)}


def route_reasons(line: dict, runs: list[dict], agreed: dict, pack: BlockedCreditPack, threshold: float) -> list[str]:
    """Every reason that sends this line to the CA. Empty list = auto-decided."""
    reasons = []
    invalid = [r for r in runs if not r["valid"]]
    if invalid:
        reasons.append(f"validation failed on {len(invalid)}/{agreed['of']} runs: {invalid[0]['error']}")
    if len(agreed["candidates"]) > 1:
        reasons.append(f"runs disagree: {agreed['candidates']}")
    if agreed["rule_id"] not in (None, NONE_ID):
        clause, _ = pack.resolve(agreed["rule_id"])
        if clause.ambiguity == "high":
            reasons.append(f"{clause.id} is marked ambiguity: high")
        if clause.needs_business_profile:
            reasons.append(f"{clause.id} depends on the business profile")
    if line["taxable_value"] > threshold:
        reasons.append(f"taxable value Rs. {line['taxable_value']:,.0f} > Rs. {threshold:,.0f}")
    return reasons
