# GST ITC Eligibility Reviewer (prototype)

AI-assisted review of GST Input Tax Credit eligibility under Sections 16 and 17(5) of India's CGST Act, 2017,
for CA firms. The spec is the written brief: [docs/GST_ITC_Brief.pdf](docs/GST_ITC_Brief.pdf).

> **Work in progress.** The full README (architecture, how to run, results, failures) comes in the final
> phase. All data in this repo is **synthetic**.

## Status
- [x] Rule pack draft (`rules/`), pending human verification: see [docs/rule_pack_verification.md](docs/rule_pack_verification.md)
- [ ] Section 16 checks
- [ ] Synthetic data and gold labels
- [ ] LangGraph pipeline with CA review (interrupt/resume)
- [ ] OpenRouter client
- [ ] Streamlit UI
- [ ] Evaluation

## Quick start (so far)
```bash
python -m venv .venv && . .venv/bin/activate   # Python 3.11
pip install -r requirements.txt
python -m pytest -q
```
