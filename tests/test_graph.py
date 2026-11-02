"""End to end in mock mode: interrupt once with the whole queue, resume with Command, persist to SQLite."""
import pytest
from langgraph.types import Command

from itc.graph import build_graph, open_checkpointer, thread_config
from itc.llm.mock import MockLLM

PERIOD = "2026-10"


@pytest.fixture
def db(tmp_path):
    return str(tmp_path / "checkpoints.sqlite")


def start(db, client="SW"):
    app = build_graph(MockLLM(), checkpointer=open_checkpointer(db))
    cfg = thread_config(client, PERIOD, "mock")
    out = app.invoke({"client_id": client, "period": PERIOD, "mode": "mock"}, cfg)
    return app, cfg, out


def queue_of(out):
    assert len(out["__interrupt__"]) == 1  # one interrupt, not one per line
    return out["__interrupt__"][0].value["queue"]


def test_runs_to_interrupt_with_whole_queue(db):
    app, cfg, out = start(db)
    queue = queue_of(out)
    routed = sorted(lid for lid, r in out["routing"].items() if r["routed"])
    assert sorted(q["line_id"] for q in queue) == routed and len(routed) > 1
    assert app.get_state(cfg).next == ("ca_review",)
    assert "final_labels" not in out


def test_state_records_versions(db):
    _, _, out = start(db)
    assert out["rule_pack_version"] == "2026.11.0"
    assert out["model_id"] == MockLLM.model_id
    assert out["prompt_version"] == "classify_v1"
    assert len(out["llm_raw"]) == 2 * 3  # 16 lines -> 2 batches x 3 runs


def test_resume_accept_and_override(db):
    app, cfg, out = start(db)
    queue = queue_of(out)
    decisions = {q["line_id"]: {"action": "accept"} for q in queue}
    decisions["SW-14"] = {"action": "override", "label": "Blocked", "rule_id": "S17_5_H",
                          "reason": "Gift, not personal consumption", "reviewer": "CA Test"}
    final = app.invoke(Command(resume={"decisions": decisions}), cfg)["final_labels"]
    assert app.get_state(cfg).next == ()
    assert final["SW-14"]["decided_by"] == "CA Test (override)" and final["SW-14"]["primary_rule_id"] == "S17_5_H"
    assert final["SW-02"]["decided_by"] == "CA (accepted)" and final["SW-02"]["label"] == "Blocked"
    assert final["SW-01"]["decided_by"] == "auto" and final["SW-01"]["label"] == "Deferred"
    assert all(f["label"] in {"Eligible", "Blocked", "Deferred"} for f in final.values())


def test_injection_line_is_routed_not_auto_eligible(db):
    _, _, out = start(db)
    r = out["routing"]["SW-05"]
    assert r["routed"] and r["provisional_label"] == "Blocked" and r["agreement"] == "2/3"


def test_invented_citation_is_rejected_and_routed(db):
    _, _, out = start(db)
    assert any("S17_5_B_I_HOTEL" in e for e in out["validation_errors"]["SW-12"])
    assert out["routing"]["SW-12"]["routed"]


def test_override_without_reason_reinterrupts(db):
    app, cfg, out = start(db)
    queue = queue_of(out)
    bad = {q["line_id"]: {"action": "accept"} for q in queue}
    bad["SW-02"] = {"action": "override", "label": "Eligible", "reason": "  "}
    again = app.invoke(Command(resume={"decisions": bad}), cfg)
    problems = again["__interrupt__"][0].value["problems"]
    assert any("SW-02" in p and "reason" in p for p in problems)
    assert app.get_state(cfg).next == ("ca_review",)


@pytest.mark.parametrize("decision,fragment", [
    ({"action": "override", "label": "Eligible", "rule_id": "S17_5_MADE_UP", "reason": "x"}, "not in the rule pack"),
    ({"action": "maybe"}, "SW-02"),
])
def test_invalid_decisions_reinterrupt(db, decision, fragment):
    app, cfg, out = start(db)
    bad = {q["line_id"]: {"action": "accept"} for q in queue_of(out)}
    bad["SW-02"] = decision
    problems = app.invoke(Command(resume={"decisions": bad}), cfg)["__interrupt__"][0].value["problems"]
    assert any(fragment in p for p in problems)


def test_missing_decision_reinterrupts(db):
    app, cfg, out = start(db)
    problems = app.invoke(Command(resume={"decisions": {}}), cfg)["__interrupt__"][0].value["problems"]
    assert any("no decision" in p for p in problems)


def test_resume_after_reopening_the_database(db):
    """A run can pause, the process can exit, and a new process resumes from SQLite."""
    _, cfg, out = start(db)
    queue = queue_of(out)
    app2 = build_graph(MockLLM(), checkpointer=open_checkpointer(db))
    assert app2.get_state(cfg).next == ("ca_review",)
    final = app2.invoke(Command(resume={"decisions": {q["line_id"]: {"action": "accept"} for q in queue}}), cfg)
    assert len(final["final_labels"]) == 16


def test_history_is_the_audit_trail(db):
    app, cfg, out = start(db)
    app.invoke(Command(resume={"decisions": {q["line_id"]: {"action": "accept"} for q in queue_of(out)}}), cfg)
    steps = [s.metadata.get("step") for s in app.get_state_history(cfg)]
    assert len(steps) >= 8  # input + 7 nodes, each checkpointed


def test_threads_are_isolated(db):
    app, cfg_sw, _ = start(db, "SW")
    _, cfg_cab, out_cab = start(db, "CAB")
    assert app.get_state(cfg_sw).values["client_id"] == "SW"
    assert out_cab["client_id"] == "CAB" and all(l.startswith("CAB") for l in out_cab["routing"])


def test_no_review_path_goes_straight_to_report(db, monkeypatch):
    import itc.graph as graph
    monkeypatch.setattr(graph, "route_reasons", lambda *a, **k: [])
    app = graph.build_graph(MockLLM(), checkpointer=open_checkpointer(db))
    cfg = thread_config("CAT", PERIOD, "mock")
    out = app.invoke({"client_id": "CAT", "period": PERIOD, "mode": "mock"}, cfg)
    assert "__interrupt__" not in out and len(out["final_labels"]) == 11
    assert all(f["decided_by"] == "auto" for f in out["final_labels"].values())


def test_period_outside_rule_pack_is_refused(db):
    app = build_graph(MockLLM(), checkpointer=open_checkpointer(db))
    with pytest.raises(Exception):
        app.invoke({"client_id": "SW", "period": "2018-06", "mode": "mock"}, thread_config("SW", "2018-06", "mock"))
