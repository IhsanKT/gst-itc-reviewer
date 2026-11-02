# Run inside an activated virtualenv (or override: make test PY=.venv/bin/python).
PY ?= python

.PHONY: setup test eval eval-mock app

setup:
	$(PY) -m pip install -r requirements.txt

test:
	$(PY) -m pytest -q

eval:
	$(PY) -m eval.run_eval

eval-mock:
	$(PY) -m eval.run_eval --mock

app:
	$(PY) -m streamlit run app.py
