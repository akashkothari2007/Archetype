.PHONY: install demo test serve

install:
	pip install -e ".[dev]"

demo:
	python -m plancheck.demo

test:
	PLANCHECK_STUB_DELAY_MS=0 pytest

serve:
	uvicorn plancheck.api.main:app --reload --port 8000
