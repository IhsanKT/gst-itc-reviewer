# Pre-registered evaluation targets

Fixed on 2026-11-02, before the evaluation code was written and before any run, mock or live. They are
copied unchanged to the top of every results file. Changing a prompt, rule-pack setting or threshold after
seeing results is logged as a new version (for example `prompts/classify_v2.md`) and reported separately.

**What is scored.** The system's labels **before** CA review: the provisional label for routed lines and the
final label for auto-decided lines. The CA step is not simulated. Gold labels: `data/gold_labels.csv`, 40
synthetic lines, committed before any classifier code.

| # | Metric | Definition | Target |
|---|--------|-----------|--------|
| 1 | **Critical error rate** | Lines where gold = Blocked, predicted = Eligible, and the line was NOT routed to the CA | **0** (zero tolerance) |
| 2 | Label accuracy | Predicted label = gold label, all 40 lines | ≥ 85% |
| 3 | Citation accuracy (exact) | Primary rule ID = gold `expected_rule_id`, reported separately from label accuracy | ≥ 75% |
| 4 | Auto-decision precision | Label accuracy on lines NOT routed to the CA | ≥ 95% |
| 5 | Review rate | Share of lines routed to the CA | ≤ 40% (the brief's "still saves time" range). **Expected to be missed** with the current settings: every rule marked `needs_business_profile` routes by design, and so does every line above Rs. 50,000. Reported honestly either way. |
| 6 | Run-to-run agreement | Share of lines where all 3 runs give the same valid rule ID | ≥ 90% |
| 7 | Ambiguous-tier routing | Share of `tier = ambiguous` gold lines that are routed to the CA | 100% |
| 8 | Prompt injection | Injected-instruction lines that end up auto-decided as Eligible | 0 |
| 9 | Baselines | The system beats both baselines (keyword classifier; same LLM without the rule pack) on label accuracy and on clause-level citation accuracy | by ≥ 10 points each; if not, that is the finding |

**Baselines** replace only the `classify_17_5` node. They use the same §16 checks and the same label
precedence, so the comparison isolates the probabilistic step. Baselines have no routing, so every line is an
auto-decision. The no-rule-pack baseline runs once per batch (a free-tier budget decision), so it has no
agreement score. It cites clauses as free text, so it is compared with the system at clause level
("17(5)(b)(i)" plus "exception applies yes/no"), not by exact ID.
