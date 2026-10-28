.PHONY: install test run
install:
	pip install -e ".[dev]"
test:
	python -m pytest --cov=agent_lab --cov-report=term-missing
run:
	agent-lab run --report reports/latest.md
