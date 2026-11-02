import pytest
import yaml

from itc.config import ROOT
from itc.rulepack import (
    NONE_ID,
    BlockedCreditPack,
    ConditionPack,
    is_valid_citation,
    load_packs,
)

PERIOD = "2026-10"


@pytest.fixture(scope="module")
def packs():
    return load_packs(PERIOD)


def test_every_17_5_clause_present_for_current_period(packs):
    blocked, _ = packs
    expected = {
        "S17_5_A", "S17_5_AA", "S17_5_AB",
        "S17_5_B_I_FOOD", "S17_5_B_I_BEAUTY_HEALTH", "S17_5_B_I_VEHICLE_HIRE", "S17_5_B_I_INSURANCE",
        "S17_5_B_II", "S17_5_B_III", "S17_5_C", "S17_5_D", "S17_5_E", "S17_5_F", "S17_5_FA",
        "S17_5_G", "S17_5_H", "S17_5_I",
    }
    assert {r.id for r in blocked.rules} == expected


def test_section16_pack_has_checks(packs):
    _, conditions = packs
    ids = {r.id for r in conditions.rules}
    assert {"S16_2_A", "S16_2_AA", "S16_2_B", "S16_2_PROVISO_180", "S16_4"} <= ids
    assert conditions.get("S16_4").outcome_on_fail == "Blocked"
    assert conditions.get("S16_2_AA").outcome_on_fail == "Deferred"


def test_versions_recorded(packs):
    blocked, conditions = packs
    assert blocked.version == conditions.version == "2026.11.0"
    assert blocked.period == PERIOD


def test_effective_dating_selects_one_version_of_clause_i():
    old, _ = load_packs("2023-09")
    mid, _ = load_packs("2024-06")
    new, _ = load_packs(PERIOD)
    assert "129" in old.get("S17_5_I").text
    assert mid.get("S17_5_I").text == "any tax paid in accordance with the provisions of section 74."
    assert "2023-24" in new.get("S17_5_I").text


def test_csr_clause_absent_before_it_was_inserted():
    old, _ = load_packs("2023-09")
    assert "S17_5_FA" not in old.citation_ids
    assert not is_valid_citation("S17_5_FA", old)


def test_clause_d_uses_plant_and_machinery_for_every_period():
    for period in ("2023-09", PERIOD):
        blocked, _ = load_packs(period)
        assert "plant and machinery" in blocked.get("S17_5_D").text
        assert "plant or machinery" not in blocked.get("S17_5_D").text


def test_period_before_coverage_is_rejected():
    with pytest.raises(ValueError, match="out of scope"):
        load_packs("2018-06")


@pytest.mark.parametrize("rule_id", ["S17_5_A", "S17_5_A.EX_PASSENGER_TRANSPORT", NONE_ID])
def test_known_citations_accepted(packs, rule_id):
    assert is_valid_citation(rule_id, packs[0])


@pytest.mark.parametrize(
    "rule_id",
    ["S17_5_Z", "17(5)(a)", "s17_5_a", "S17_5_A.EX_MADE_UP", "Eligible", "", None, 42, "S16_4"],
)
def test_unknown_citations_rejected(packs, rule_id):
    # S16_4 is a real rule, but it is not a 17(5) answer the classifier may give.
    assert not is_valid_citation(rule_id, packs[0])


def test_resolve_exception_to_parent_clause(packs):
    rule, ex = packs[0].resolve("S17_5_A.EX_PASSENGER_TRANSPORT")
    assert rule.id == "S17_5_A"
    assert ex.id == "S17_5_A.EX_PASSENGER_TRANSPORT"
    assert packs[0].resolve(NONE_ID) == (None, None)
    with pytest.raises(KeyError):
        packs[0].resolve("S17_5_NOPE")


def _raw(name):
    with open(ROOT / "rules" / name, encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_overlapping_versions_rejected():
    data = _raw("cgst_17_5.yaml")
    dup = dict(next(r for r in data["rules"] if r["id"] == "S17_5_G"))
    data["rules"].append(dup)
    with pytest.raises(ValueError, match="overlap"):
        BlockedCreditPack.model_validate(data)


def test_exception_ids_must_be_namespaced():
    data = _raw("cgst_17_5.yaml")
    data["rules"][0]["exceptions"][0]["id"] = "EX_LOOSE"
    with pytest.raises(ValueError, match="must start with"):
        BlockedCreditPack.model_validate(data)


def test_unknown_field_rejected():
    data = _raw("cgst_16.yaml")
    data["rules"][0]["typo_field"] = 1
    with pytest.raises(ValueError):
        ConditionPack.model_validate(data)
