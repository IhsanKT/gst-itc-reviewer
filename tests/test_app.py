"""Drives the Streamlit UI headlessly: run, override one line with a reason, submit, resume to completion."""
import pytest
from streamlit.testing.v1 import AppTest

from itc.config import ROOT

THREAD = "SW:2026-10:mock"


@pytest.fixture
def at(tmp_path, monkeypatch):
    monkeypatch.setenv("ITC_CHECKPOINT_DB", str(tmp_path / "ui.sqlite"))
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
    assert not app.exception
    return app


def submit(app):
    next(b for b in app.button if b.label.startswith("Submit")).click().run()
    assert not app.exception


def test_run_review_override_and_resume(at):
    at.button[0].click().run()  # Run review
    assert not at.exception
    assert any("Paused at **ca_review**" in w.value for w in at.warning)
    queue = [r for r in at.radio if (r.key or "").startswith("act_")]
    assert len(queue) == 10

    next(r for r in queue if r.key.endswith("SW-14")).set_value("Override").run()
    at.text_input(key=f"why_{THREAD}_SW-14").input("Gift to a relative; cite (h)").run()
    at.selectbox(key=f"rule_{THREAD}_SW-14").set_value("S17_5_H").run()
    submit(at)
    assert any("Run complete" in s.value for s in at.success)
    assert dict((m.label, m.value) for m in at.metric)["Reviewed by CA"] == "10"


def test_override_without_reason_is_blocked_in_the_ui(at):
    at.button[0].click().run()
    queue = [r for r in at.radio if (r.key or "").startswith("act_")]
    queue[0].set_value("Override").run()
    submit(at)
    assert any("needs a reason" in e.value for e in at.error)
    assert any("Paused at **ca_review**" in w.value for w in at.warning)  # still paused
