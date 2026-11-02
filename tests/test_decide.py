import pytest

from itc.decide import agreement, compose_label, label_from_17_5, route_reasons
from itc.rulepack import load_packs

PACK, _ = load_packs("2026-10")
THRESHOLD = 50000


def check(rule_id, passed, outcome="Deferred"):
    return {"rule_id": rule_id, "passed": passed, "outcome_on_fail": outcome, "detail": ""}


ALL_PASS = [check("S16_2_A", True), check("S16_2_AA", True), check("S16_2_B", True),
            check("S16_2_PROVISO_180", True), check("S16_4", True, "Blocked")]


def with_fail(rule_id, outcome="Deferred"):
    return [check(c["rule_id"], c["rule_id"] != rule_id, c["outcome_on_fail"]) for c in ALL_PASS]


def run(rule_id, valid=True, error=None):
    return {"rule_id": rule_id, "reason": "", "valid": valid, "error": error}


# ---------------------------------------------------------------- labels

@pytest.mark.parametrize("rule_id,label", [
    ("S17_5_A", "Blocked"), ("S17_5_A.EX_PASSENGER_TRANSPORT", "Eligible"), ("NONE", "Eligible"), (None, "Blocked"),
])
def test_label_from_17_5(rule_id, label):
    assert label_from_17_5(rule_id, PACK) == label


def test_eligible_when_everything_passes():
    out = compose_label(ALL_PASS, "NONE", PACK)
    assert out == {"label": "Eligible", "primary_rule_id": "NONE", "cited_rule_ids": []}


def test_exception_is_cited_on_eligible():
    out = compose_label(ALL_PASS, "S17_5_A.EX_PASSENGER_TRANSPORT", PACK)
    assert out["label"] == "Eligible" and out["primary_rule_id"] == "S17_5_A.EX_PASSENGER_TRANSPORT"


def test_blocked_beats_deferred():
    out = compose_label(with_fail("S16_2_AA"), "S17_5_B_I_FOOD", PACK)
    assert out["label"] == "Blocked" and out["primary_rule_id"] == "S17_5_B_I_FOOD"
    assert out["cited_rule_ids"] == ["S16_2_AA", "S17_5_B_I_FOOD"]


def test_deferred_beats_eligible():
    out = compose_label(with_fail("S16_2_PROVISO_180"), "NONE", PACK)
    assert out["label"] == "Deferred" and out["primary_rule_id"] == "S16_2_PROVISO_180"


def test_time_barred_is_blocked_even_if_17_5_eligible():
    out = compose_label(with_fail("S16_4"), "S17_5_A.EX_PASSENGER_TRANSPORT", PACK)
    assert out["label"] == "Blocked" and out["primary_rule_id"] == "S16_4"


def test_deferred_primary_follows_statute_order():
    checks = [check("S16_2_PROVISO_180", False), check("S16_2_A", False), check("S16_4", True, "Blocked")]
    assert compose_label(checks, "NONE", PACK)["primary_rule_id"] == "S16_2_A"


def test_no_valid_answer_is_conservative():
    out = compose_label(ALL_PASS, None, PACK)
    assert out["label"] == "Blocked" and out["primary_rule_id"] is None


# ---------------------------------------------------------------- agreement

def test_unanimous():
    a = agreement([run("S17_5_G")] * 3, 3)
    assert a["rule_id"] == "S17_5_G" and a["agree"] == 3 and a["unanimous"]


def test_majority():
    a = agreement([run("S17_5_H"), run("S17_5_H"), run("S17_5_B_I_FOOD")], 3)
    assert a["rule_id"] == "S17_5_H" and a["agree"] == 2 and not a["unanimous"]


def test_tie_prefers_blocking_clause():
    a = agreement([run("NONE"), run("S17_5_A"), run(None, False, "bad")], 3)
    assert a["rule_id"] == "S17_5_A" and a["agree"] == 1


def test_tie_between_exception_and_none_is_deterministic():
    a = agreement([run("NONE"), run("S17_5_A.EX_PASSENGER_TRANSPORT")], 3)
    assert a["rule_id"] == "NONE"


def test_invalid_runs_do_not_count():
    a = agreement([run("S17_5_G"), run("S17_5_G"), run("S17_5_FAKE", False, "unknown")], 3)
    assert a["agree"] == 2 and not a["unanimous"]


def test_no_valid_runs():
    a = agreement([run(None, False, "x")] * 3, 3)
    assert a["rule_id"] is None and a["agree"] == 0


# ---------------------------------------------------------------- routing rules

LINE = {"taxable_value": 10000}


def reasons(runs, line=LINE):
    return route_reasons(line, runs, agreement(runs, 3), PACK, THRESHOLD)


def test_low_value_unanimous_low_ambiguity_is_auto():
    assert reasons([run("S17_5_B_II")] * 3) == []
    assert reasons([run("NONE")] * 3) == []


def test_disagreement_routes():
    assert any("disagree" in r for r in reasons([run("S17_5_G"), run("S17_5_G"), run("NONE")]))


def test_high_ambiguity_routes():
    assert any("ambiguity: high" in r for r in reasons([run("S17_5_G")] * 3))


def test_business_profile_rule_routes_even_via_exception():
    assert any("business profile" in r for r in reasons([run("S17_5_A.EX_PASSENGER_TRANSPORT")] * 3))


def test_value_above_threshold_routes():
    assert any("> Rs. 50,000" in r for r in reasons([run("NONE")] * 3, {"taxable_value": 50001}))


def test_value_at_threshold_is_auto():
    assert reasons([run("NONE")] * 3, {"taxable_value": 50000}) == []


def test_validation_failure_routes():
    out = reasons([run("NONE"), run("NONE"), run("S17_5_X", False, "citation 'S17_5_X' is not in rule pack")])
    assert any("validation failed" in r for r in out)
