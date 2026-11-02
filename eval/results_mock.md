# Evaluation results: MOCK
> **MOCK RUN: not a model result.** The classifier here is the deterministic keyword-and-profile
> fake in `itc/llm/mock.py`, written by the same author as the gold labels, so its accuracy says
> nothing about an LLM. This file exists to show the pipeline and metrics run end to end without a
> key. Live results go to `eval/results.md`.

Generated 2026-11-02T13:46:52+00:00 · mode **mock** · model `mock/keyword-profile-v1` · prompt `classify_v1` · rule pack `2026.11.0` · temperature 0.0 · 3 runs/line · batch 8 · threshold Rs. 50,000 · network calls this run: 18 · cache hits: None

## Pre-registered targets (copied from eval/targets.md)

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

## Scorecard

| Metric | Target | Result | Met |
|---|---|---|---|
| Critical error rate (Blocked -> Eligible, not routed) | 0 | 0 lines | yes |
| Label accuracy | >= 85% | 100.0% | yes |
| Citation accuracy (exact ID) | >= 75% | 100.0% | yes |
| Auto-decision precision | >= 95% | 100.0% | yes |
| Review rate | <= 40% | 70.0% | **no** |
| Run-to-run agreement (3/3) | >= 90% | 92.5% | yes |
| Ambiguous tier routed to CA | 100% | 85.7% | **no** |
| Injected lines auto-decided Eligible | 0 | 0 lines | yes |
| Beats keyword baseline by >= 10 pts (label / clause citation) | >= +10 / >= +10 | +30.0 / +32.5 pts | yes |

## System vs baselines

| Metric | System | Keyword baseline | Same LLM, no rule pack |
|---|---|---|---|
| Label accuracy | 100.0% | 70.0% | not run (live only) |
| Citation accuracy (exact ID) | 100.0% | 67.5% | not run (live only) |
| Citation accuracy (clause level) | 100.0% | 67.5% | not run (live only) |
| Critical errors (count) | 0 | 0 | not run (live only) |
| Critical error rate (of gold Blocked) | 0.0% | 0.0% | not run (live only) |
| Review rate | 70.0% | 0.0% | not run (live only) |
| Auto-decision precision | 100.0% | 70.0% | not run (live only) |

Run-to-run agreement (all 3 runs identical): **92.5%** of lines.

## Per tier

| Group | n | System label acc. | System clause cit. | Routed | Keyword label acc. | No-rule-pack label acc. |
|---|---|---|---|---|---|---|
| ambiguous | 7 | 100.0% | 100.0% | 85.7% | 71.4% | n/a |
| clear | 22 | 100.0% | 100.0% | 50.0% | 90.9% | n/a |
| exception | 11 | 100.0% | 100.0% | 100.0% | 27.3% | n/a |

## Per category

| Group | n | System label acc. | System clause cit. | Routed | Keyword label acc. | No-rule-pack label acc. |
|---|---|---|---|---|---|---|
| A | 5 | 100.0% | 100.0% | 100.0% | 40.0% | n/a |
| AA | 1 | 100.0% | 100.0% | 100.0% | 0.0% | n/a |
| AB | 3 | 100.0% | 100.0% | 100.0% | 33.3% | n/a |
| B_II | 1 | 100.0% | 100.0% | 0.0% | 100.0% | n/a |
| B_III | 1 | 100.0% | 100.0% | 0.0% | 100.0% | n/a |
| B_I_BEAUTY_HEALTH | 1 | 100.0% | 100.0% | 100.0% | 100.0% | n/a |
| B_I_FOOD | 7 | 100.0% | 100.0% | 100.0% | 71.4% | n/a |
| B_I_INSURANCE | 1 | 100.0% | 100.0% | 100.0% | 100.0% | n/a |
| B_I_VEHICLE_HIRE | 1 | 100.0% | 100.0% | 100.0% | 0.0% | n/a |
| C | 3 | 100.0% | 100.0% | 66.7% | 66.7% | n/a |
| D | 1 | 100.0% | 100.0% | 100.0% | 100.0% | n/a |
| E | 1 | 100.0% | 100.0% | 0.0% | 100.0% | n/a |
| FA | 1 | 100.0% | 100.0% | 100.0% | 100.0% | n/a |
| G | 1 | 100.0% | 100.0% | 100.0% | 100.0% | n/a |
| H | 1 | 100.0% | 100.0% | 100.0% | 100.0% | n/a |
| NONE | 4 | 100.0% | 100.0% | 0.0% | 75.0% | n/a |
| S16 | 7 | 100.0% | 100.0% | 42.9% | 85.7% | n/a |

## Adversarial subset

| Group | n | System label acc. | System clause cit. | Routed | Keyword label acc. | No-rule-pack label acc. |
|---|---|---|---|---|---|---|
| hinglish | 4 | 100.0% | 100.0% | 100.0% | 75.0% | n/a |
| injection | 1 | 100.0% | 100.0% | 100.0% | 100.0% | n/a |
| misleading | 7 | 100.0% | 100.0% | 71.4% | 57.1% | n/a |
| none | 24 | 100.0% | 100.0% | 58.3% | 75.0% | n/a |
| paired | 4 | 100.0% | 100.0% | 100.0% | 50.0% | n/a |

## Confusion matrix (system, gold rows x predicted columns, before CA review)

| gold \ predicted | Eligible | Blocked | Deferred |
|---|---|---|---|
| Eligible | 16 | 0 | 0 |
| Blocked | 0 | 20 | 0 |
| Deferred | 0 | 0 | 4 |

## Failure table: 0 lines where the label or the exact citation is wrong

Causes are first-pass, assigned automatically by `likely_cause()` from the gold and predicted IDs.

| Line | Gold | Predicted | Routed | Agreement | Likely cause | Description |
|---|---|---|---|---|---|---|

<details><summary>All 40 lines</summary>

| Line | Tier | Gold | System | Routed | Keyword | No rule pack |
|---|---|---|---|---|---|---|
| SW-01 | clear | Deferred `S16_2_AA` | Deferred `S16_2_AA` 3/3 | no | Deferred `S16_2_AA` | - |
| SW-02 | clear | Blocked `S17_5_A` | Blocked `S17_5_A` 3/3 | yes | Blocked `S17_5_A` | - |
| SW-03 | clear | Blocked `S17_5_AB` | Blocked `S17_5_AB` 3/3 | yes | Blocked `S17_5_AB` | - |
| SW-04 | clear | Blocked `S17_5_B_I_FOOD` | Blocked `S17_5_B_I_FOOD` 3/3 | yes | Blocked `S17_5_B_I_FOOD` | - |
| SW-05 | clear | Blocked `S17_5_B_I_FOOD` | Blocked `S17_5_B_I_FOOD` 2/3 | yes | Blocked `S17_5_B_I_FOOD` | - |
| SW-06 | exception | Blocked `S17_5_B_I_FOOD` | Blocked `S17_5_B_I_FOOD` 3/3 | yes | Blocked `S17_5_B_I_FOOD` | - |
| SW-07 | clear | Blocked `S17_5_B_I_BEAUTY_HEALTH` | Blocked `S17_5_B_I_BEAUTY_HEALTH` 3/3 | yes | Blocked `S17_5_B_I_BEAUTY_HEALTH` | - |
| SW-08 | clear | Blocked `S17_5_B_II` | Blocked `S17_5_B_II` 3/3 | no | Blocked `S17_5_B_II` | - |
| SW-09 | clear | Blocked `S17_5_B_III` | Blocked `S17_5_B_III` 3/3 | no | Blocked `S17_5_B_III` | - |
| SW-10 | clear | Eligible `NONE` | Eligible `NONE` 3/3 | no | Blocked `S17_5_B_III` | - |
| SW-11 | clear | Eligible `NONE` | Eligible `NONE` 3/3 | no | Eligible `NONE` | - |
| SW-12 | ambiguous | Blocked `S17_5_B_I_FOOD` | Blocked `S17_5_B_I_FOOD` 2/3 | yes | Blocked `S17_5_B_I_FOOD` | - |
| SW-13 | clear | Blocked `S17_5_FA` | Blocked `S17_5_FA` 3/3 | yes | Blocked `S17_5_FA` | - |
| SW-14 | ambiguous | Blocked `S17_5_G` | Blocked `S17_5_G` 3/3 | yes | Blocked `S17_5_G` | - |
| SW-15 | clear | Blocked `S17_5_C` | Blocked `S17_5_C` 3/3 | yes | Blocked `S17_5_C` | - |
| SW-16 | ambiguous | Eligible `NONE` | Eligible `NONE` 3/3 | no | Eligible `NONE` | - |
| CAB-01 | exception | Eligible `S17_5_A.EX_PASSENGER_TRANSPORT` | Eligible `S17_5_A.EX_PASSENGER_TRANSPORT` 3/3 | yes | Blocked `S17_5_A` | - |
| CAB-02 | exception | Eligible `S17_5_AB.EX_SPECIFIED_PURPOSE` | Eligible `S17_5_AB.EX_SPECIFIED_PURPOSE` 3/3 | yes | Blocked `S17_5_AB` | - |
| CAB-03 | exception | Eligible `S17_5_AB.EX_SPECIFIED_PURPOSE` | Eligible `S17_5_AB.EX_SPECIFIED_PURPOSE` 3/3 | yes | Blocked `S17_5_AB` | - |
| CAB-04 | exception | Eligible `S17_5_B_I_VEHICLE_HIRE.EX_SPECIFIED_PURPOSE` | Eligible `S17_5_B_I_VEHICLE_HIRE.EX_SPECIFIED_PURPOSE` 3/3 | yes | Blocked `S17_5_B_I_VEHICLE_HIRE` | - |
| CAB-05 | exception | Blocked `S17_5_A` | Blocked `S17_5_A` 3/3 | yes | Blocked `S17_5_G` | - |
| CAB-06 | clear | Blocked `S17_5_B_I_FOOD` | Blocked `S17_5_B_I_FOOD` 3/3 | yes | Blocked `S17_5_B_I_FOOD` | - |
| CAB-07 | clear | Eligible `NONE` | Eligible `NONE` 3/3 | no | Eligible `NONE` | - |
| CAB-08 | clear | Blocked `S17_5_D` | Blocked `S17_5_D` 3/3 | yes | Blocked `S17_5_D` | - |
| CAB-09 | clear | Blocked `S16_4` | Blocked `S16_4` 3/3 | yes | Blocked `S16_4` | - |
| CAB-10 | clear | Deferred `S16_2_PROVISO_180` | Deferred `S16_2_PROVISO_180` 3/3 | no | Deferred `S16_2_PROVISO_180` | - |
| CAB-11 | clear | Eligible `NONE` | Eligible `NONE` 3/3 | no | Eligible `NONE` | - |
| CAB-12 | ambiguous | Blocked `S17_5_B_I_INSURANCE` | Blocked `S17_5_B_I_INSURANCE` 3/3 | yes | Blocked `S17_5_B_I_INSURANCE` | - |
| CAB-13 | exception | Eligible `NONE` | Eligible `NONE` 3/3 | yes | Blocked `S17_5_A` | - |
| CAT-01 | exception | Eligible `S17_5_B_I_FOOD.EX_SAME_CATEGORY` | Eligible `S17_5_B_I_FOOD.EX_SAME_CATEGORY` 3/3 | yes | Blocked `S17_5_B_I_FOOD` | - |
| CAT-02 | ambiguous | Eligible `S17_5_B_I_FOOD.EX_EMPLOYER_OBLIGATION` | Eligible `S17_5_B_I_FOOD.EX_EMPLOYER_OBLIGATION` 3/3 | yes | Blocked `S17_5_B_I_FOOD` | - |
| CAT-03 | exception | Eligible `NONE` | Eligible `NONE` 3/3 | yes | Blocked `S17_5_A` | - |
| CAT-04 | exception | Eligible `S17_5_AA.EX_GOODS_TRANSPORT` | Eligible `S17_5_AA.EX_GOODS_TRANSPORT` 3/3 | yes | Blocked `S17_5_AA` | - |
| CAT-05 | ambiguous | Eligible `S17_5_C.EX_PLANT_AND_MACHINERY` | Eligible `S17_5_C.EX_PLANT_AND_MACHINERY` 3/3 | yes | Blocked `S17_5_C` | - |
| CAT-06 | clear | Blocked `S17_5_E` | Blocked `S17_5_E` 3/3 | no | Blocked `S17_5_E` | - |
| CAT-07 | ambiguous | Blocked `S17_5_H` | Blocked `S17_5_H` 2/3 | yes | Blocked `S17_5_H` | - |
| CAT-08 | clear | Deferred `S16_2_B` | Deferred `S16_2_B` 3/3 | yes | Deferred `S16_2_B` | - |
| CAT-09 | exception | Blocked `S16_4` | Blocked `S16_4` 3/3 | yes | Blocked `S16_4` | - |
| CAT-10 | clear | Eligible `NONE` | Eligible `NONE` 3/3 | no | Eligible `NONE` | - |
| CAT-11 | clear | Deferred `S16_2_A` | Deferred `S16_2_A` 3/3 | no | Blocked `S17_5_B_I_FOOD` | - |

</details>
