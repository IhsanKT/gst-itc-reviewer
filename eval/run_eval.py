"""Scores the system and two baselines against data/gold_labels.csv.

    python -m eval.run_eval            # live model via the committed cache (needs OPENROUTER_API_KEY on a miss)
    python -m eval.run_eval --mock     # deterministic fake LLM; writes results_mock.*, never results.*

The system is scored on labels BEFORE CA review (provisional label for routed lines). Targets are fixed in
eval/targets.md and copied to the top of the results file.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

from baselines import keyword
from itc.config import ROOT, load_config
from itc.decide import compose_label
from itc.graph import build_graph, make_llm, open_checkpointer, thread_config
from itc.inputs import available_periods, load_clients
from itc.llm import LLMError, LLMRequest
from itc.llm.prompt import build_messages, norules_response_format
from itc.rulepack import NONE_ID, load_packs

EVAL = ROOT / "eval"
LABELS = ["Eligible", "Blocked", "Deferred"]
SYSTEMS = ["system", "keyword", "no_rule_pack"]


# ---------------------------------------------------------------- running

def run_system(mode: str, cfg: dict):
    llm = make_llm(mode, cfg)
    app = build_graph(llm, cfg, checkpointer=open_checkpointer(":memory:"))
    states = []
    for client in load_clients(cfg):
        for period in available_periods(client.client_id, cfg):
            tc = thread_config(client.client_id, period, mode)
            app.invoke({"client_id": client.client_id, "period": period, "mode": mode}, tc)
            states.append(app.get_state(tc).values)
    return llm, states


def run_no_rule_pack(llm, states: list[dict], cfg: dict) -> dict[str, dict]:
    """Baseline 2: same model and profile, prompt without the rule pack, one run per batch."""
    version = cfg["prompt"]["baseline_no_rules"]
    size = cfg["llm"]["batch_size"]
    out = {}
    for st in states:
        lines = st["invoice_lines"]
        for start in range(0, len(lines), size):
            batch = lines[start:start + size]
            req = LLMRequest(messages=build_messages(version, batch, st["client_profile"], None),
                             response_format=norules_response_format(), run_index=0, prompt_version=version,
                             rule_pack_version=st["rule_pack_version"], lines=batch, profile=st["client_profile"])
            try:
                items = {i["line_id"]: i for i in json.loads(llm.complete(req))["lines"]}
            except (LLMError, json.JSONDecodeError, KeyError, TypeError) as e:
                items, err = {}, str(e)
            for ln in batch:
                it = items.get(ln["line_id"])
                out[ln["line_id"]] = ({"clause": norm_clause(it.get("clause")), "exception": bool(it.get("exception_applies")),
                                       "reason": it.get("reason", ""), "error": None} if isinstance(it, dict)
                                      else {"clause": None, "exception": False, "reason": "", "error": "no valid answer"})
    return out


def norm_clause(raw) -> str | None:
    if not isinstance(raw, str):
        return None
    s = re.sub(r"\s+", "", raw.lower()).replace("section", "")
    if s in ("", "none", "null", "n/a", "na"):
        return NONE_ID
    m = re.search(r"17\(5\)((?:\([a-z]+\))+)", s)
    return f"17(5){m.group(1)}" if m else s


# ---------------------------------------------------------------- scoring helpers

def clause_key(rule_id: str | None, pack) -> tuple:
    """Clause-level citation: ('17(5)(b)(i)', exception?) so free-text baselines can be compared fairly."""
    if rule_id is None:
        return ("INVALID", False)
    if rule_id == NONE_ID:
        return (NONE_ID, False)
    if rule_id.startswith("S16"):
        return (rule_id, False)
    clause, ex = pack.resolve(rule_id)
    return (clause.clause, ex is not None)


def likely_cause(gold: dict, pred: dict, pack) -> str:
    g, p = gold["expected_rule_id"], pred["primary_rule_id"]
    if p is None:
        return "no valid classifier output on any run"
    if g.startswith("S16") or (p or "").startswith("S16"):
        return "section 16 outcome differs (check data or s.16 logic)"
    if g == NONE_ID:
        return "false positive: a 17(5) clause was applied to a line no clause covers"
    if p == NONE_ID:
        return "missed a 17(5) clause"
    gc, gx = pack.resolve(g)
    pc, px = pack.resolve(p)
    if gc.id == pc.id and gx and not px:
        return "exception missed: clause right, exception not recognised"
    if gc.id == pc.id and px and not gx:
        return "exception over-applied: credit wrongly restored"
    if gc.id == pc.id:
        return "right clause, different exception"
    return "wrong clause" + (" (label still right)" if gold["expected_label"] == pred["label"] else "")


def pct(n, d):
    return round(100 * n / d, 1) if d else None


def fmt(v):
    return "n/a" if v is None else f"{v}%"


# ---------------------------------------------------------------- main evaluation

def evaluate(mode: str):
    cfg = load_config()
    gold = {r["line_id"]: r for r in csv.DictReader(open(ROOT / "data" / "gold_labels.csv", encoding="utf-8"))}
    llm, states = run_system(mode, cfg)
    no_rules = run_no_rule_pack(llm, states, cfg) if mode == "live" else None

    rows = []
    for st in states:
        pack, _ = load_packs(st["period"], cfg)
        for ln in st["invoice_lines"]:
            lid = ln["line_id"]
            g = gold[lid]
            rt = st["routing"][lid]
            s16 = st["s16_results"][lid]
            sys_pred = {"label": rt["provisional_label"], "primary_rule_id": rt["provisional_primary_rule_id"]}
            kw_rule = keyword.classify(ln["description"])
            kw = compose_label(s16, kw_rule, pack)
            row = {
                "line_id": lid, "client_id": st["client_id"], "description": ln["description"],
                "tier": g["tier"], "category": g["category"], "adversarial": g["adversarial"],
                "gold_label": g["expected_label"], "gold_rule_id": g["expected_rule_id"],
                "system": {**sys_pred, "routed": rt["routed"], "reasons": rt["reasons"], "agreement": rt["agreement"],
                           "unanimous": rt["unanimous"], "candidates": rt["candidates"],
                           "clause_key": clause_key(sys_pred["primary_rule_id"], pack)},
                "keyword": {"label": kw["label"], "primary_rule_id": kw["primary_rule_id"], "routed": False,
                            "clause_key": clause_key(kw["primary_rule_id"], pack)},
                "gold_clause_key": clause_key(g["expected_rule_id"], pack),
            }
            if row["system"]["label"] != g["expected_label"] or sys_pred["primary_rule_id"] != g["expected_rule_id"]:
                row["system"]["likely_cause"] = likely_cause(g, sys_pred, pack)
            if no_rules is not None:
                nr = no_rules[lid]
                blocked = nr["clause"] not in (None, NONE_ID) and not nr["exception"]
                surrogate = None if nr["clause"] is None else ("S17_5_G" if blocked else NONE_ID)  # label only
                comp = compose_label(s16, surrogate, pack)
                key = (comp["primary_rule_id"], False) if (comp["primary_rule_id"] or "").startswith("S16") \
                    else ("INVALID", False) if nr["clause"] is None else (nr["clause"], nr["exception"] and nr["clause"] != NONE_ID)
                row["no_rule_pack"] = {"label": comp["label"], "clause": nr["clause"], "exception": nr["exception"],
                                       "routed": False, "clause_key": key, "error": nr["error"]}
            rows.append(row)

    results = {
        "mode": mode,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "run": {
            "model_id": states[0]["model_id"], "prompt_version": states[0]["prompt_version"],
            "baseline_prompt_version": cfg["prompt"]["baseline_no_rules"] if mode == "live" else None,
            "rule_pack_version": states[0]["rule_pack_version"], "temperature": states[0]["temperature"],
            "runs_per_line": cfg["llm"]["runs_per_line"], "batch_size": cfg["llm"]["batch_size"],
            "review_threshold_inr": cfg["routing"]["review_threshold_inr"],
            "network_calls": getattr(getattr(llm, "inner", llm), "calls", None),
            "cache_hits": getattr(llm, "hits", None),
        },
        "metrics": {s: metrics(rows, s) for s in SYSTEMS if s in rows[0]},
        "lines": rows,
    }
    results["targets"] = scorecard(results["metrics"])
    return results


def metrics(rows: list[dict], s: str) -> dict:
    n = len(rows)
    right = [r for r in rows if r[s]["label"] == r["gold_label"]]
    critical = [r["line_id"] for r in rows
                if r["gold_label"] == "Blocked" and r[s]["label"] == "Eligible" and not r[s]["routed"]]
    auto = [r for r in rows if not r[s]["routed"]]
    m = {
        "n": n,
        "label_accuracy": pct(len(right), n),
        "citation_accuracy_exact": pct(sum(r[s].get("primary_rule_id") == r["gold_rule_id"] for r in rows), n)
        if s != "no_rule_pack" else None,
        "citation_accuracy_clause_level": pct(sum(tuple(r[s]["clause_key"]) == tuple(r["gold_clause_key"]) for r in rows), n),
        "critical_errors": critical,
        "critical_error_rate": pct(len(critical), sum(r["gold_label"] == "Blocked" for r in rows)),
        "auto_decisions": len(auto),
        "auto_decision_precision": pct(sum(r[s]["label"] == r["gold_label"] for r in auto), len(auto)),
        "review_rate": pct(n - len(auto), n),
    }
    if s == "system":
        m["agreement_unanimous_rate"] = pct(sum(r["system"]["unanimous"] for r in rows), n)
        amb = [r for r in rows if r["tier"] == "ambiguous"]
        m["ambiguous_routed_rate"] = pct(sum(r["system"]["routed"] for r in amb), len(amb))
        inj = [r for r in rows if r["adversarial"] == "injection"]
        m["injection_auto_eligible"] = [r["line_id"] for r in inj
                                        if r["system"]["label"] == "Eligible" and not r["system"]["routed"]]
        m["confusion"] = {g: {p: sum(r["gold_label"] == g and r["system"]["label"] == p for r in rows) for p in LABELS}
                          for g in LABELS}
    for group in ("tier", "category", "adversarial"):
        buckets = defaultdict(list)
        for r in rows:
            key = r[group].split(":")[0]
            buckets[key].append(r)
        m[f"by_{group}"] = {
            k: {"n": len(v), "label_accuracy": pct(sum(r[s]["label"] == r["gold_label"] for r in v), len(v)),
                "citation_accuracy_clause_level": pct(sum(tuple(r[s]["clause_key"]) == tuple(r["gold_clause_key"]) for r in v), len(v)),
                "routed": pct(sum(r[s]["routed"] for r in v), len(v))}
            for k, v in sorted(buckets.items())
        }
    return m


def scorecard(ms: dict) -> list[dict]:
    s = ms["system"]

    def row(name, target, value, met):
        return {"metric": name, "target": target, "result": value, "met": met}

    out = [
        row("Critical error rate (Blocked -> Eligible, not routed)", "0", f"{len(s['critical_errors'])} lines",
            len(s["critical_errors"]) == 0),
        row("Label accuracy", ">= 85%", fmt(s["label_accuracy"]), s["label_accuracy"] >= 85),
        row("Citation accuracy (exact ID)", ">= 75%", fmt(s["citation_accuracy_exact"]), s["citation_accuracy_exact"] >= 75),
        row("Auto-decision precision", ">= 95%", fmt(s["auto_decision_precision"]),
            s["auto_decision_precision"] is not None and s["auto_decision_precision"] >= 95),
        row("Review rate", "<= 40%", fmt(s["review_rate"]), s["review_rate"] <= 40),
        row("Run-to-run agreement (3/3)", ">= 90%", fmt(s["agreement_unanimous_rate"]), s["agreement_unanimous_rate"] >= 90),
        row("Ambiguous tier routed to CA", "100%", fmt(s["ambiguous_routed_rate"]), s["ambiguous_routed_rate"] == 100),
        row("Injected lines auto-decided Eligible", "0", f"{len(s['injection_auto_eligible'])} lines",
            not s["injection_auto_eligible"]),
    ]
    for b in ("keyword", "no_rule_pack"):
        if b in ms:
            dl = s["label_accuracy"] - ms[b]["label_accuracy"]
            dc = s["citation_accuracy_clause_level"] - ms[b]["citation_accuracy_clause_level"]
            out.append(row(f"Beats {b} baseline by >= 10 pts (label / clause citation)", ">= +10 / >= +10",
                           f"{dl:+.1f} / {dc:+.1f} pts", dl >= 10 and dc >= 10))
    return out


# ---------------------------------------------------------------- report

def to_markdown(res: dict) -> str:
    targets = (EVAL / "targets.md").read_text(encoding="utf-8").split("\n", 1)[1].strip()
    ms, run = res["metrics"], res["run"]
    L = []
    if res["mode"] == "mock":
        L += ["# Evaluation results: MOCK",
              "> **MOCK RUN: not a model result.** The classifier here is the deterministic keyword-and-profile",
              "> fake in `itc/llm/mock.py`, written by the same author as the gold labels, so its accuracy says",
              "> nothing about an LLM. This file exists to show the pipeline and metrics run end to end without a",
              "> key. Live results go to `eval/results.md`.", ""]
    else:
        L += ["# Evaluation results", ""]
    L += [f"Generated {res['generated_at']} · mode **{res['mode']}** · model `{run['model_id']}` · prompt "
          f"`{run['prompt_version']}` · rule pack `{run['rule_pack_version']}` · temperature {run['temperature']} · "
          f"{run['runs_per_line']} runs/line · batch {run['batch_size']} · threshold Rs. {run['review_threshold_inr']:,} · "
          f"network calls this run: {run['network_calls']} · cache hits: {run['cache_hits']}", ""]
    L += ["## Pre-registered targets (copied from eval/targets.md)", "", targets, ""]
    L += ["## Scorecard", "", "| Metric | Target | Result | Met |", "|---|---|---|---|"]
    L += [f"| {t['metric']} | {t['target']} | {t['result']} | {'yes' if t['met'] else '**no**'} |" for t in res["targets"]]
    L += ["", "## System vs baselines", "",
          "| Metric | System | Keyword baseline | Same LLM, no rule pack |", "|---|---|---|---|"]

    def cell(s, k):
        if s not in ms:
            return "not run (live only)"
        v = ms[s].get(k)
        return "n/a" if v is None else (f"{len(v)}" if isinstance(v, list) else f"{v}%")
    for k, name in [("label_accuracy", "Label accuracy"), ("citation_accuracy_exact", "Citation accuracy (exact ID)"),
                    ("citation_accuracy_clause_level", "Citation accuracy (clause level)"),
                    ("critical_errors", "Critical errors (count)"), ("critical_error_rate", "Critical error rate (of gold Blocked)"),
                    ("review_rate", "Review rate"), ("auto_decision_precision", "Auto-decision precision")]:
        L.append(f"| {name} | {cell('system', k)} | {cell('keyword', k)} | {cell('no_rule_pack', k)} |")
    s = ms["system"]
    L += ["", f"Run-to-run agreement (all 3 runs identical): **{s['agreement_unanimous_rate']}%** of lines.", ""]
    for group, title in [("tier", "Per tier"), ("category", "Per category"), ("adversarial", "Adversarial subset")]:
        L += [f"## {title}", "", "| Group | n | System label acc. | System clause cit. | Routed | Keyword label acc. | No-rule-pack label acc. |",
              "|---|---|---|---|---|---|---|"]
        for k, v in s[f"by_{group}"].items():
            kw = ms["keyword"][f"by_{group}"][k]["label_accuracy"]
            nr = ms["no_rule_pack"][f"by_{group}"][k]["label_accuracy"] if "no_rule_pack" in ms else None
            L.append(f"| {k} | {v['n']} | {fmt(v['label_accuracy'])} | {fmt(v['citation_accuracy_clause_level'])} | "
                     f"{fmt(v['routed'])} | {fmt(kw)} | {fmt(nr)} |")
        L.append("")
    L += ["## Confusion matrix (system, gold rows x predicted columns, before CA review)", "",
          "| gold \\ predicted | " + " | ".join(LABELS) + " |", "|---" * (len(LABELS) + 1) + "|"]
    L += [f"| {g} | " + " | ".join(str(s["confusion"][g][p]) for p in LABELS) + " |" for g in LABELS]
    fails = [r for r in res["lines"] if "likely_cause" in r["system"]]
    L += ["", f"## Failure table: {len(fails)} lines where the label or the exact citation is wrong", "",
          "Causes are first-pass, assigned automatically by `likely_cause()` from the gold and predicted IDs.", "",
          "| Line | Gold | Predicted | Routed | Agreement | Likely cause | Description |", "|---|---|---|---|---|---|---|"]
    for r in fails:
        sy = r["system"]
        L.append(f"| {r['line_id']} | {r['gold_label']} `{r['gold_rule_id']}` | {sy['label']} `{sy['primary_rule_id']}` | "
                 f"{'yes' if sy['routed'] else '**no**'} | {sy['agreement']} | {sy['likely_cause']} | {r['description'][:70]} |")
    L += ["", "<details><summary>All 40 lines</summary>", "",
          "| Line | Tier | Gold | System | Routed | Keyword | No rule pack |", "|---|---|---|---|---|---|---|"]
    for r in res["lines"]:
        nr = f"{r['no_rule_pack']['label']} ({r['no_rule_pack']['clause']})" if "no_rule_pack" in r else "-"
        L.append(f"| {r['line_id']} | {r['tier']} | {r['gold_label']} `{r['gold_rule_id']}` | {r['system']['label']} "
                 f"`{r['system']['primary_rule_id']}` {r['system']['agreement']} | {'yes' if r['system']['routed'] else 'no'} | "
                 f"{r['keyword']['label']} `{r['keyword']['primary_rule_id']}` | {nr} |")
    L += ["", "</details>", ""]
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mock", action="store_true", help="use the deterministic fake LLM (no key, no network)")
    args = ap.parse_args(argv)
    mode = "mock" if args.mock else "live"
    res = evaluate(mode)
    if mode == "live":
        failed_calls = sum(1 for r in res["lines"] if any("LLM call failed" in x for x in r["system"]["reasons"]))
        if failed_calls == len(res["lines"]):
            sys.exit("Every LLM call failed (no API key and no cached responses?). Set OPENROUTER_API_KEY in .env, "
                     "or run with --mock.")
    stem = "results_mock" if mode == "mock" else "results"
    (EVAL / f"{stem}.json").write_text(json.dumps(res, indent=2, ensure_ascii=False, default=list), encoding="utf-8")
    (EVAL / f"{stem}.md").write_text(to_markdown(res), encoding="utf-8")
    met = sum(t["met"] for t in res["targets"])
    print(f"[{mode}] label acc {res['metrics']['system']['label_accuracy']}% · critical errors "
          f"{len(res['metrics']['system']['critical_errors'])} · review rate {res['metrics']['system']['review_rate']}% · "
          f"targets met {met}/{len(res['targets'])} -> eval/{stem}.md")


if __name__ == "__main__":
    main()
