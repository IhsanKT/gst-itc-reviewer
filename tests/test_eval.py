import pytest

from baselines import keyword
from eval.run_eval import evaluate, norm_clause, to_markdown


@pytest.mark.parametrize("raw,expected", [
    ("17(5)(b)(i)", "17(5)(b)(i)"), ("Section 17(5)(a)", "17(5)(a)"), (" 17 (5) (fa) ", "17(5)(fa)"),
    ("NONE", "NONE"), ("none", "NONE"), ("", "NONE"), (None, None),
])
def test_norm_clause(raw, expected):
    assert norm_clause(raw) == expected


def test_keyword_baseline_ignores_profile_and_exceptions():
    assert keyword.classify("Maruti Suzuki Dzire Tour S (5 seater)") == "S17_5_A"
    assert keyword.classify("Air tickets for client meeting") == "S17_5_B_III"  # a known keyword false positive
    assert keyword.classify("AWS cloud hosting") == "NONE"


def test_mock_eval_end_to_end():
    res = evaluate("mock")
    m = res["metrics"]
    assert m["system"]["n"] == 40 and "no_rule_pack" not in m  # baseline 2 needs the live model
    assert {"label_accuracy", "citation_accuracy_exact", "critical_errors", "review_rate",
            "auto_decision_precision", "confusion"} <= set(m["system"])
    md = to_markdown(res)
    assert md.startswith("# Evaluation results: MOCK") and "Pre-registered targets" in md
