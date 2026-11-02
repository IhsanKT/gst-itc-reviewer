"""CA review UI for the GST ITC eligibility pipeline. Run: streamlit run app.py

The UI never decides anything itself: it starts a LangGraph run, shows its checkpointed state, and resumes
the paused ca_review node with Command(resume=...). All data is synthetic.
"""
from __future__ import annotations

import json

import pandas as pd
import streamlit as st
from langgraph.types import Command

from itc.config import ROOT, get_api_key, load_config
from itc.graph import build_graph, make_llm, open_checkpointer, thread_config
from itc.inputs import available_periods, load_clients
from itc.rulepack import load_packs

CFG = load_config()
FINAL_LABELS = ["Eligible", "Blocked", "Deferred"]
LABEL_STYLE = {  # muted, one hue family per label
    "Eligible": ("#E4EEE7", "#2D5641"),
    "Blocked": ("#F1E3E3", "#782E2E"),
    "Deferred": ("#F2EBDB", "#66501F"),
    "Needs CA review": ("#E1E7F0", "#2D4869"),
}

st.set_page_config(page_title="GST ITC Reviewer", page_icon=":material/fact_check:", layout="wide")
st.markdown(
    """<style>
    .block-container {padding-top: 2.2rem; max-width: 1280px;}
    .badge {display:inline-block; padding:2px 10px; border-radius:999px; font-size:0.78rem; font-weight:600;}
    .muted {color:#5B6675; font-size:0.86rem;}
    .rule {background:#FFFFFF; border-left:3px solid #3B5B7A; padding:8px 12px; font-size:0.86rem; color:#2B3440;}
    div[data-testid="stMetricValue"] {font-size:1.6rem;}
    </style>""",
    unsafe_allow_html=True,
)


def badge(label: str) -> str:
    bg, fg = LABEL_STYLE.get(label, ("#EDF0F4", "#334155"))
    return f'<span class="badge" style="background:{bg};color:{fg}">{label}</span>'


def style_label(value: str) -> str:
    bg, fg = LABEL_STYLE.get(value, ("transparent", "inherit"))
    return f"background-color:{bg}; color:{fg}; font-weight:600"


@st.cache_resource
def checkpointer():
    return open_checkpointer(config=CFG)


@st.cache_resource
def graph_for(mode: str):
    return build_graph(make_llm(mode, CFG), CFG, checkpointer())


def rupees(v: float) -> str:
    return f"Rs. {v:,.0f}"


# ---------------------------------------------------------------- sidebar

clients = {c.client_id: c for c in load_clients(CFG)}
with st.sidebar:
    st.markdown("#### Engagement")
    cid = st.selectbox("Client", list(clients), format_func=lambda c: clients[c].legal_name)
    period = st.selectbox("Tax period", available_periods(cid, CFG))
    st.markdown("#### Classifier")
    mode_choice = st.segmented_control("LLM mode", ["Mock", "Live"], default="Mock",
                                       help="Mock: deterministic fake LLM, no key, no network. "
                                            "Live: the pinned OpenRouter model, behind the on-disk cache.")
    mode = "live" if mode_choice == "Live" else "mock"
    if mode == "live" and get_api_key():
        st.caption("OpenRouter key found. Uncached requests use free-tier quota; cached ones cost nothing.")
    elif mode == "live":
        st.warning("No OPENROUTER_API_KEY. Live mode serves cached responses only; any uncached request fails "
                   "and the line goes to the CA.", icon=":material/key_off:")
    else:
        st.caption("Mock results are not model results.")
    run_clicked = st.button("Run review", type="primary", width="stretch")
    reset_clicked = st.button("Clear this run", width="stretch")
    st.divider()
    blocked_pack, _ = load_packs(period, CFG)
    st.markdown(
        f"<div class='muted'>Model <code>{CFG['llm']['model_id'] if mode == 'live' else 'mock/keyword-profile-v1'}</code><br>"
        f"Prompt <code>{CFG['prompt']['classify']}</code> · Rule pack <code>{blocked_pack.version}</code><br>"
        f"{CFG['llm']['runs_per_line']} runs per line · CA threshold {rupees(CFG['routing']['review_threshold_inr'])}"
        f"<br><br>All data is SYNTHETIC. Decision support only: the CA signs off.</div>",
        unsafe_allow_html=True,
    )

app = graph_for(mode)
tc = thread_config(cid, period, mode)
thread_id = tc["configurable"]["thread_id"]

if reset_clicked:
    checkpointer().delete_thread(thread_id)
    st.rerun()
if run_clicked:
    checkpointer().delete_thread(thread_id)  # one thread = one client + period (+ mode)
    with st.spinner("Running section 16 checks and the 17(5) classifier (3 runs per line)..."):
        app.invoke({"client_id": cid, "period": period, "mode": mode}, tc)
    st.rerun()

snap = app.get_state(tc)
state = snap.values
profile = clients[cid]

st.title("GST ITC Eligibility Review")
st.markdown(f"<div class='muted'>{profile.legal_name} · GSTIN {profile.gstin} · tax period {period} · "
            f"thread <code>{thread_id}</code> · CGST Act 2017, Sections 16 and 17(5)</div>", unsafe_allow_html=True)
st.write("")

if not state:
    st.info("Choose a client and tax period in the sidebar, then click **Run review**. The pipeline runs the "
            "deterministic section 16 checks, asks the classifier three times per line, validates every citation "
            "against the rule pack, and pauses for CA review if any line is routed.", icon=":material/play_circle:")
    with st.container(border=True):
        st.markdown(f"**Business profile**: {profile.business_activity}")
        st.markdown(f"**Outward supplies**: {', '.join(profile.outward_supplies)}")
        if profile.notes:
            st.markdown(f"**Notes**: {profile.notes}")
    st.stop()

# ---------------------------------------------------------------- derived view of the state

pending = snap.next == ("ca_review",)
interrupt_value = snap.interrupts[0].value if snap.interrupts else None
final = state.get("final_labels") or {}
routing = state["routing"]
lines = state["invoice_lines"]


def shown_label(lid: str) -> str:
    if lid in final:
        return final[lid]["label"]
    return "Needs CA review" if routing[lid]["routed"] else routing[lid]["provisional_label"]


labels = {ln["line_id"]: shown_label(ln["line_id"]) for ln in lines}
n_routed = sum(r["routed"] for r in routing.values())
cols = st.columns(6)
cols[0].metric("Lines", len(lines))
for col, name in zip(cols[1:4], FINAL_LABELS):
    col.metric(name, sum(v == name for v in labels.values()))
cols[4].metric("Awaiting CA" if pending else "Reviewed by CA", n_routed)
cols[5].metric("Review rate", f"{100 * n_routed / len(lines):.0f}%")
if pending:
    st.warning(f"Paused at **ca_review**: {n_routed} lines are waiting for CA decisions. Open the review queue "
               "tab. The run is checkpointed, so you can close the app and resume later.", icon=":material/pause_circle:")
else:
    st.success("Run complete. Every line carries a final label, its citations, evidence and the decision maker.",
               icon=":material/task_alt:")

tab_results, tab_review, tab_audit, tab_eval, tab_rules = st.tabs(
    ["Results", f"CA review queue ({n_routed if pending else 0})", "Audit log", "Evaluation", "Client and rule pack"])

# ---------------------------------------------------------------- results

with tab_results:
    view = st.segmented_control("Show", ["All lines", "Routed to CA", "Auto-decided"], default="All lines",
                                key="results_filter")
    keep = [ln for ln in lines if view in (None, "All lines")
            or (view == "Routed to CA") == routing[ln["line_id"]]["routed"]]
    table = pd.DataFrame([{
        "Line": ln["line_id"],
        "Label": labels[ln["line_id"]],
        "Provisional": routing[ln["line_id"]]["provisional_label"],
        "Rule": (final.get(ln["line_id"], {}).get("primary_rule_id") if ln["line_id"] in final
                 else routing[ln["line_id"]]["provisional_primary_rule_id"]) or "-",
        "Agreement": routing[ln["line_id"]]["agreement"],
        "Taxable value": ln["taxable_value"],
        "Routed": "Yes" if routing[ln["line_id"]]["routed"] else "No",
        "Decided by": final.get(ln["line_id"], {}).get("decided_by", "pending" if routing[ln["line_id"]]["routed"] else "auto"),
        "Description": ln["description"],
    } for ln in keep])
    if not table.empty:
        st.dataframe(
            table.style.map(style_label, subset=["Label", "Provisional"]),
            hide_index=True, width="stretch",
            column_config={"Taxable value": st.column_config.NumberColumn(format="Rs. %d"),
                           "Description": st.column_config.TextColumn(width="large")},
        )
    st.markdown("##### Evidence per line")
    _, conditions = load_packs(period, CFG)
    for ln in keep:
        lid = ln["line_id"]
        rt = routing[lid]
        with st.expander(f"{lid} · {labels[lid]} · {ln['description'][:90]}"):
            head = badge(labels[lid])
            if rt["routed"] and lid not in final:
                head += f" &nbsp;provisional {badge(rt['provisional_label'])}"
            st.markdown(head + f" &nbsp;<span class='muted'>agreement {rt['agreement']} · cites "
                        f"{', '.join(rt['provisional_cited_rule_ids']) or 'no rule (NONE)'}</span>", unsafe_allow_html=True)
            left, right = st.columns([1, 1.3])
            with left:
                st.markdown("**Invoice text** (treated as data, never as instructions)")
                st.markdown(f"> {ln['description']}")
                st.markdown(
                    f"<div class='muted'>{ln['supplier_name']} · GSTIN {ln['supplier_gstin'] or 'missing'}<br>"
                    f"Invoice {ln['invoice_no']} (normalised {ln['invoice_no_normalised']}) · {ln['invoice_date']} · "
                    f"{ln['doc_type']}<br>Taxable {rupees(ln['taxable_value'])} · GST {ln['gst_rate']}% "
                    f"({rupees(ln['tax_amount'])}) · HSN/SAC {ln['hsn'] or '-'} · received {ln['received_on'] or 'not yet'}</div>",
                    unsafe_allow_html=True)
                st.markdown("**Routing**")
                if rt["reasons"]:
                    st.markdown("\n".join(f"- {r}" for r in rt["reasons"]))
                else:
                    st.markdown("Auto-decided: runs agree, the rule is low-risk, and the value is below the threshold.")
                if lid in final and final[lid]["ca_reason"]:
                    st.markdown(f"**CA note** ({final[lid]['decided_by']}): {final[lid]['ca_reason']}")
            with right:
                st.markdown("**Section 16 checks** (deterministic code)")
                st.dataframe(pd.DataFrame([{"Rule": c["rule_id"], "Result": "pass" if c["passed"] else f"fail -> {c['outcome_on_fail']}",
                                            "Detail": c["detail"]} for c in state["s16_results"][lid]]),
                             hide_index=True, width="stretch")
                st.markdown("**Classifier runs** (the only probabilistic step)")
                st.dataframe(pd.DataFrame([{"Run": r["run_index"], "Rule ID": r["rule_id"] or "-",
                                            "Valid": "yes" if r["valid"] else "REJECTED",
                                            "Reason / error": r["reason"] if r["valid"] else r["error"]}
                                           for r in state["llm_runs"][lid]]),
                             hide_index=True, width="stretch")
            primary = final[lid]["primary_rule_id"] if lid in final else rt["provisional_primary_rule_id"]
            if primary and primary != "NONE":
                if primary.startswith("S16"):
                    r = conditions.get(primary)
                    text = f"<b>{r.id}</b> [{r.clause}] {r.text}"
                else:
                    clause, ex = blocked_pack.resolve(primary)
                    text = f"<b>{clause.id}</b> [{clause.clause}] {clause.text}"
                    if ex:
                        text += f"<br><br><b>{ex.id}</b>: {ex.text}"
                    text += f"<br><span class='muted'>verified: {str(clause.verified).lower()} · {clause.source[:60]}</span>"
                st.markdown(f"<div class='rule'>{text}</div>", unsafe_allow_html=True)

# ---------------------------------------------------------------- CA review queue

with tab_review:
    if pending and interrupt_value:
        queue = interrupt_value["queue"]
        for p in interrupt_value.get("problems", []):
            st.error(f"Previous submission rejected: {p}")
        top = st.columns([1, 2])
        reviewer = top[0].text_input("Reviewer", value="CA", help="Recorded against every decision in the audit log.")
        top[1].markdown("<div class='muted' style='padding-top:1.9rem'>Accept keeps the provisional label. "
                        "Override needs a label and a written reason. One submission resumes the paused run.</div>",
                        unsafe_allow_html=True)
        citable = sorted(blocked_pack.citation_ids | {r.id for r in conditions.rules})
        decisions, missing = {}, []
        for q in queue:
            lid = q["line_id"]
            with st.container(border=True):
                a, b = st.columns([2.2, 1])
                with a:
                    st.markdown(f"**{lid}** · {q['supplier_name']} · {rupees(q['taxable_value'])}")
                    st.markdown(f"> {q['description']}")
                    st.markdown("<div class='muted'>Routed because: " + "; ".join(q["reasons"]) + "</div>",
                                unsafe_allow_html=True)
                with b:
                    st.markdown(f"Provisional {badge(q['provisional_label'])}<br><span class='muted'>"
                                f"{q['provisional_primary_rule_id'] or 'no valid citation'} · agreement {q['agreement']}</span>",
                                unsafe_allow_html=True)
                    action = st.radio("Decision", ["Accept", "Override"], key=f"act_{thread_id}_{lid}",
                                      horizontal=True, label_visibility="collapsed")
                if action == "Override":
                    c1, c2, c3 = st.columns([1, 1.2, 2.4])
                    new_label = c1.selectbox("Label", FINAL_LABELS, key=f"lab_{thread_id}_{lid}")
                    rule = c2.selectbox("Rule (optional)", ["-"] + citable, key=f"rule_{thread_id}_{lid}")
                    reason = c3.text_input("Reason (required)", key=f"why_{thread_id}_{lid}")
                    if not reason.strip():
                        missing.append(lid)
                    decisions[lid] = {"action": "override", "label": new_label, "reason": reason,
                                      "rule_id": None if rule == "-" else rule, "reviewer": reviewer or "CA"}
                else:
                    decisions[lid] = {"action": "accept", "reviewer": reviewer or "CA"}
        if st.button(f"Submit {len(queue)} decisions and resume the run", type="primary"):
            if missing:
                st.error(f"Every override needs a reason: {', '.join(missing)}")
            else:
                with st.spinner("Resuming the graph from its checkpoint..."):
                    app.invoke(Command(resume={"decisions": decisions}), tc)
                st.rerun()
    elif state.get("ca_decisions"):
        st.markdown("CA review is complete. Decisions recorded for this run:")
        st.dataframe(pd.DataFrame([{
            "Line": lid, "Provisional": routing[lid]["provisional_label"], "Decision": d["action"],
            "Final label": final[lid]["label"], "Rule": final[lid]["primary_rule_id"] or "-",
            "Reason": d["reason"] or "-", "Reviewer": d["reviewer"], "Decided at (UTC)": d["decided_at"],
        } for lid, d in state["ca_decisions"].items()]).style.map(style_label, subset=["Provisional", "Final label"]),
            hide_index=True, width="stretch")
    else:
        st.info("No line in this run needed CA review.")

# ---------------------------------------------------------------- audit log

with tab_audit:
    meta = state.get("run_meta", {})
    st.markdown("##### Run record")
    st.dataframe(pd.DataFrame([
        ("Thread", thread_id), ("Mode", state.get("mode")), ("Rule pack version", state.get("rule_pack_version")),
        ("Model ID", state.get("model_id")), ("Prompt version", state.get("prompt_version")),
        ("Temperature", state.get("temperature")), ("Runs per line", meta.get("runs_per_line")),
        ("Batch size", meta.get("batch_size")), ("CA threshold (INR)", meta.get("review_threshold_inr")),
        ("LLM requests", meta.get("llm_requests")), ("Network calls", meta.get("llm_network_calls")),
        ("Cache hits (session)", meta.get("cache_hits")), ("Started (UTC)", meta.get("started_at")),
        ("Finished (UTC)", meta.get("finished_at", "paused at ca_review" if pending else "-")),
    ], columns=["Field", "Value"]).astype(str), hide_index=True, width="stretch")

    overrides = {lid: d for lid, d in (state.get("ca_decisions") or {}).items() if d["action"] == "override"}
    st.markdown(f"##### CA overrides ({len(overrides)})")
    if overrides:
        st.dataframe(pd.DataFrame([{"Line": lid, "Provisional": routing[lid]["provisional_label"],
                                    "Override": d["label"], "Rule": d["rule_id"] or "-", "Reason": d["reason"],
                                    "Reviewer": d["reviewer"], "At (UTC)": d["decided_at"]}
                                   for lid, d in overrides.items()]), hide_index=True, width="stretch")
    else:
        st.caption("None.")

    st.markdown("##### State history (SQLite checkpointer, newest first)")
    history = list(app.get_state_history(tc))
    st.dataframe(pd.DataFrame([{
        "Step": h.metadata.get("step"), "Created (UTC)": h.created_at, "Source": h.metadata.get("source"),
        "Next node": ", ".join(h.next) or "END", "State keys": len(h.values),
        "Checkpoint": h.config["configurable"]["checkpoint_id"][-12:],
    } for h in history]), hide_index=True, width="stretch")
    st.download_button("Download full state as JSON", json.dumps(state, indent=2, default=str),
                       file_name=f"audit_{thread_id.replace(':', '_')}.json", mime="application/json")

# ---------------------------------------------------------------- evaluation

with tab_eval:
    live, mock = ROOT / "eval" / "results.md", ROOT / "eval" / "results_mock.md"
    if live.exists():
        st.markdown(live.read_text(encoding="utf-8"), unsafe_allow_html=True)
    elif mock.exists():
        st.info("No live evaluation yet: showing the MOCK run. Live results appear here after "
                "`python -m eval.run_eval` with an OpenRouter key.", icon=":material/info:")
        st.markdown(mock.read_text(encoding="utf-8"), unsafe_allow_html=True)
    else:
        st.caption("Run `python -m eval.run_eval --mock` to generate results.")

# ---------------------------------------------------------------- client and rules

with tab_rules:
    with st.container(border=True):
        st.markdown(f"**{profile.legal_name}**: {profile.business_activity}")
        st.markdown(f"Outward supplies: {', '.join(profile.outward_supplies)}")
        if profile.notes:
            st.markdown(f"Notes: {profile.notes}")
    st.markdown(f"##### Section 17(5) rule pack {blocked_pack.version} in force for {period}")
    st.caption("Every entry is verified: false until checked by hand against the official Act "
               "(docs/rule_pack_verification.md). DRAFT = not copied from an official consolidated text.")
    st.dataframe(pd.DataFrame([{
        "ID": r.id, "Clause": r.clause, "Title": r.title, "Exceptions": len(r.exceptions),
        "Ambiguity": r.ambiguity, "Needs profile": "yes" if r.needs_business_profile else "no",
        "In force": f"{r.effective_from} to {r.effective_to or 'date'}",
        "Source": "DRAFT" if r.source.startswith("DRAFT") else "VERBATIM", "Verified": r.verified,
    } for r in blocked_pack.rules]), hide_index=True, width="stretch")
