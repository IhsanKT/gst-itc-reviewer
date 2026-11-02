"""The LangGraph state graph (Figure 1 of the brief).

START -> ingest -> section16_checks -> classify_17_5 -> validate -> route
route --(any line needs review)--> ca_review (interrupt) -> report -> END
route --(no review needed)-------> report -> END

One thread = one client + one tax period (+ mode, so Mock and Live runs never share a thread).
classify_17_5 is the only probabilistic node. ca_review interrupts once with the whole review queue and
resumes with Command(resume={"decisions": {line_id: decision}}). Every state transition is checkpointed to SQLite.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from typing import TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from pydantic import ValidationError

from itc.config import ROOT, get_api_key, load_config
from itc.decide import agreement, compose_label, route_reasons
from itc.inputs import load_client_inputs
from itc.llm import LLMError, LLMRequest
from itc.llm.cache import DiskCache
from itc.llm.client import CachedLLM, OfflineLLM, OpenRouterLLM
from itc.llm.mock import MockLLM
from itc.llm.prompt import build_messages, classify_response_format
from itc.rulepack import NONE_ID, load_packs
from itc.schemas import CADecision, ClientProfile, Gstr2bRecord, Invoice, Payment
from itc.section16 import normalise_invoice_no, run_section16
from itc.validate import validate_batch


class ITCState(TypedDict, total=False):
    # identity
    client_id: str
    period: str
    mode: str
    # inputs (ingest)
    client_profile: dict
    invoices: list[dict]
    invoice_lines: list[dict]
    gstr2b_records: list[dict]
    payment_ledger: list[dict]
    # per-line results
    s16_results: dict[str, list[dict]]
    llm_raw: list[dict]
    llm_runs: dict[str, list[dict]]
    validation_errors: dict[str, list[str]]
    routing: dict[str, dict]
    ca_decisions: dict[str, dict]
    final_labels: dict[str, dict]
    # audit
    rule_pack_version: str
    model_id: str
    prompt_version: str
    temperature: float
    run_meta: dict


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def make_llm(mode: str, config: dict | None = None):
    """mock -> deterministic fake; live -> OpenRouter behind the disk cache (cache-only if no key)."""
    cfg = (config or load_config())["llm"]
    if mode == "mock":
        return MockLLM()
    key = get_api_key()
    inner = OpenRouterLLM(cfg, key) if key else OfflineLLM(cfg["model_id"], cfg["temperature"])
    return CachedLLM(inner, DiskCache(ROOT / cfg["cache_dir"]))


def open_checkpointer(path: str | None = None, config: dict | None = None) -> SqliteSaver:
    """ITC_CHECKPOINT_DB overrides the configured file (used by the UI test to stay out of the real DB)."""
    db = path or os.environ.get("ITC_CHECKPOINT_DB") or str(ROOT / (config or load_config())["checkpoint_db"])
    return SqliteSaver(sqlite3.connect(db, check_same_thread=False))


def thread_config(client_id: str, period: str, mode: str) -> dict:
    return {"configurable": {"thread_id": f"{client_id}:{period}:{mode}"}}


def build_graph(llm, config: dict | None = None, checkpointer=None):
    cfg = config or load_config()
    llm_cfg = cfg["llm"]
    prompt_version = cfg["prompt"]["classify"]
    threshold = cfg["routing"]["review_threshold_inr"]
    runs_per_line = llm_cfg["runs_per_line"]

    # ------------------------------------------------------------------ nodes
    def ingest(state: ITCState) -> dict:
        inputs = load_client_inputs(state["client_id"], state["period"], cfg)
        blocked, _ = load_packs(state["period"], cfg)  # raises if the period is outside the pack's coverage
        lines = []
        for idx, inv in enumerate(inputs["invoices"]):
            header = inv.model_dump(mode="json", exclude={"items"})
            for item in inv.items:
                lines.append({
                    **header, **item.model_dump(mode="json"), "invoice_index": idx,
                    "invoice_no_normalised": normalise_invoice_no(inv.invoice_no or ""),
                })
        ids = [ln["line_id"] for ln in lines]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate line_id in invoice file")
        return {
            "client_profile": inputs["profile"].model_dump(mode="json"),
            "invoices": [i.model_dump(mode="json") for i in inputs["invoices"]],
            "invoice_lines": lines,
            "gstr2b_records": [r.model_dump(mode="json") for r in inputs["gstr2b"]],
            "payment_ledger": [p.model_dump(mode="json") for p in inputs["payments"]],
            "rule_pack_version": blocked.version,
            "model_id": llm.model_id,
            "prompt_version": prompt_version,
            "temperature": llm.temperature,
            "run_meta": {"started_at": _now(), "runs_per_line": runs_per_line, "batch_size": llm_cfg["batch_size"],
                         "review_threshold_inr": threshold},
        }

    def section16_checks(state: ITCState) -> dict:
        _, conditions = load_packs(state["period"], cfg)
        profile = ClientProfile.model_validate(state["client_profile"])
        gstr2b = [Gstr2bRecord.model_validate(r) for r in state["gstr2b_records"]]
        payments = [Payment.model_validate(p) for p in state["payment_ledger"]]
        results = {}
        for inv_data in state["invoices"]:
            inv = Invoice.model_validate(inv_data)
            checks = [c.model_dump() for c in run_section16(inv, gstr2b, payments, profile, state["period"], conditions)]
            for item in inv.items:
                results[item.line_id] = checks
        return {"s16_results": results}

    def classify_17_5(state: ITCState) -> dict:
        blocked, _ = load_packs(state["period"], cfg)
        lines = state["invoice_lines"]
        size = llm_cfg["batch_size"]
        allowed = sorted(blocked.citation_ids)
        raw = []
        calls_before = getattr(llm, "calls", 0) + getattr(getattr(llm, "inner", None), "calls", 0)
        for b, start in enumerate(range(0, len(lines), size)):
            batch = lines[start:start + size]
            messages = build_messages(prompt_version, batch, state["client_profile"], blocked)
            for run_index in range(runs_per_line):
                req = LLMRequest(messages=messages, response_format=classify_response_format(allowed),
                                 run_index=run_index, prompt_version=prompt_version,
                                 rule_pack_version=blocked.version, lines=batch,
                                 profile=state["client_profile"], allowed_ids=allowed)
                try:
                    text, error = llm.complete(req), None
                except LLMError as e:
                    text, error = None, str(e)
                raw.append({"batch": b, "run_index": run_index, "line_ids": [ln["line_id"] for ln in batch],
                            "response_text": text, "error": error})
        calls_after = getattr(llm, "calls", 0) + getattr(getattr(llm, "inner", None), "calls", 0)
        meta = {**state["run_meta"], "llm_requests": len(raw), "llm_network_calls": calls_after - calls_before,
                "cache_hits": getattr(llm, "hits", None)}
        return {"llm_raw": raw, "run_meta": meta}

    def validate(state: ITCState) -> dict:
        blocked, _ = load_packs(state["period"], cfg)
        runs: dict[str, list[dict]] = {ln["line_id"]: [] for ln in state["invoice_lines"]}
        errors: dict[str, list[str]] = {lid: [] for lid in runs}
        raw_checked = []
        for r in state["llm_raw"]:
            per_line, batch_errors = validate_batch(r["response_text"], r["line_ids"], blocked, r["error"])
            raw_checked.append({**r, "validation_errors": batch_errors})
            for lid, run in per_line.items():
                runs[lid].append({"run_index": r["run_index"], **run})
                if run["error"]:
                    errors[lid].append(f"run {r['run_index']}: {run['error']}")
        return {"llm_raw": raw_checked, "llm_runs": runs, "validation_errors": errors}

    def route(state: ITCState) -> dict:
        blocked, _ = load_packs(state["period"], cfg)
        routing = {}
        for ln in state["invoice_lines"]:
            lid = ln["line_id"]
            runs = state["llm_runs"][lid]
            agreed = agreement(runs, runs_per_line)
            provisional = compose_label(state["s16_results"][lid], agreed["rule_id"], blocked)
            reasons = route_reasons(ln, runs, agreed, blocked, threshold)
            routing[lid] = {
                "routed": bool(reasons), "reasons": reasons,
                "rule_id_17_5": agreed["rule_id"], "agreement": f"{agreed['agree']}/{agreed['of']}",
                "unanimous": agreed["unanimous"], "candidates": agreed["candidates"],
                "provisional_label": provisional["label"],
                "provisional_primary_rule_id": provisional["primary_rule_id"],
                "provisional_cited_rule_ids": provisional["cited_rule_ids"],
            }
        return {"routing": routing}

    def ca_review(state: ITCState) -> dict:
        queue = [
            {"line_id": ln["line_id"], "description": ln["description"], "supplier_name": ln["supplier_name"],
             "taxable_value": ln["taxable_value"], **state["routing"][ln["line_id"]]}
            for ln in state["invoice_lines"] if state["routing"][ln["line_id"]]["routed"]
        ]
        expected = {q["line_id"] for q in queue}
        blocked, conditions = load_packs(state["period"], cfg)
        citable = blocked.citation_ids | {r.id for r in conditions.rules}
        problems: list[str] = []
        while True:  # one interrupt per submission; re-asks only if the CA's submission is invalid
            answer = interrupt({"kind": "ca_review", "client_id": state["client_id"], "period": state["period"],
                                "queue": queue, "problems": problems})
            decisions, problems = _parse_decisions(answer, expected, citable)
            if not problems:
                break
        stamped = {lid: {**d, "decided_at": _now()} for lid, d in decisions.items()}
        return {"ca_decisions": stamped}

    def report(state: ITCState) -> dict:
        blocked, conditions = load_packs(state["period"], cfg)
        decisions = state.get("ca_decisions") or {}
        final = {}
        for ln in state["invoice_lines"]:
            lid = ln["line_id"]
            rt = state["routing"][lid]
            d = decisions.get(lid)
            label, primary, cited = rt["provisional_label"], rt["provisional_primary_rule_id"], rt["provisional_cited_rule_ids"]
            decided_by, ca_reason = "auto", ""
            if rt["routed"] and d is None:  # unreachable via the graph: ca_review needs a decision per routed line
                label, decided_by = "Needs CA review", "pending"
            elif rt["routed"] and d["action"] == "accept":
                decided_by, ca_reason = f"{d['reviewer']} (accepted)", d["reason"]
            elif rt["routed"]:
                label, primary, decided_by, ca_reason = d["label"], d["rule_id"], f"{d['reviewer']} (override)", d["reason"]
                cited = [primary] if primary else []
            final[lid] = {
                "label": label, "primary_rule_id": primary, "cited_rule_ids": cited,
                "decided_by": decided_by, "ca_reason": ca_reason,
                "routed": rt["routed"], "route_reasons": rt["reasons"],
                "provisional_label": rt["provisional_label"], "agreement": rt["agreement"],
                "rule_text": _rule_text(primary, blocked, conditions),
                "rule_pack_version": state["rule_pack_version"], "model_id": state["model_id"],
                "prompt_version": state["prompt_version"],
            }
        meta = {**state["run_meta"], "finished_at": _now()}
        return {"final_labels": final, "run_meta": meta}

    def needs_review(state: ITCState) -> str:
        return "ca_review" if any(r["routed"] for r in state["routing"].values()) else "report"

    g = StateGraph(ITCState)
    for name, fn in [("ingest", ingest), ("section16_checks", section16_checks), ("classify_17_5", classify_17_5),
                     ("validate", validate), ("route", route), ("ca_review", ca_review), ("report", report)]:
        g.add_node(name, fn)
    g.add_edge(START, "ingest")
    g.add_edge("ingest", "section16_checks")
    g.add_edge("section16_checks", "classify_17_5")
    g.add_edge("classify_17_5", "validate")
    g.add_edge("validate", "route")
    g.add_conditional_edges("route", needs_review, {"ca_review": "ca_review", "report": "report"})
    g.add_edge("ca_review", "report")
    g.add_edge("report", END)
    return g.compile(checkpointer=checkpointer)


def _parse_decisions(answer, expected: set[str], citable: set[str]) -> tuple[dict, list[str]]:
    """Resume payload: {"decisions": {line_id: decision}}. The wrapper key matters: LangGraph reads a bare dict
    whose keys could be interrupt IDs (including an empty dict) as a per-interrupt mapping, not as a value."""
    problems = []
    if not isinstance(answer, dict) or not isinstance(answer.get("decisions"), dict):
        return {}, ['resume value must be {"decisions": {line_id: decision}}']
    answer = answer["decisions"]
    decisions = {}
    for lid in sorted(expected):
        if lid not in answer:
            problems.append(f"{lid}: no decision")
            continue
        try:
            d = CADecision.model_validate(answer[lid])
        except ValidationError as e:
            problems.append(f"{lid}: {e.errors()[0]['msg']}")
            continue
        if d.rule_id is not None and d.rule_id not in citable:
            problems.append(f"{lid}: rule {d.rule_id!r} is not in the rule pack")
            continue
        decisions[lid] = d.model_dump()
    for lid in set(answer) - expected:
        problems.append(f"{lid}: not in the review queue")
    return decisions, problems


def _rule_text(rule_id: str | None, blocked, conditions) -> str:
    if rule_id in (None, NONE_ID):
        return "No Section 17(5) clause applies." if rule_id == NONE_ID else ""
    if rule_id.startswith("S16"):
        try:
            r = conditions.get(rule_id)
            return f"[{r.clause}] {r.text}"
        except KeyError:
            return ""
    try:
        clause, ex = blocked.resolve(rule_id)
    except KeyError:
        return ""
    text = f"[{clause.clause}] {clause.text}"
    return text + (f"\nException: {ex.text}" if ex else "")
