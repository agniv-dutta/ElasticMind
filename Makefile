.PHONY: setup test lint fmt run demo up down logs train train-demo smoke

PYTHON ?= python
PIP ?= pip

setup:
	$(PIP) install -e ./ml -e ./backend -e ./loadgen -e ./target_app -e ./gateway
	$(PIP) install pytest ruff black pre-commit
	pre-commit install || true
	cd frontend && npm install

test:
	$(PYTHON) -m pytest ml backend loadgen target_app gateway -q

lint:
	ruff check ml backend loadgen target_app gateway experiments
	black --check ml backend loadgen target_app gateway experiments
	cd frontend && npm run lint --if-present
	cd frontend && npx tsc --noEmit

fmt:
	ruff check --fix ml backend loadgen target_app gateway experiments
	black ml backend loadgen target_app gateway experiments

train:
	$(PYTHON) -m ml.data.generate --profile diurnal --days 14 --out ml/data/generated/diurnal.parquet
	$(PYTHON) -m ml.train --data ml/data/generated/diurnal.parquet

train-demo:
	$(PYTHON) -m experiments.train_demo

run:
	docker compose up --build backend gateway

up:
	docker compose up --build -d backend gateway frontend

demo:
	bash scripts/demo.sh

demo-ps:
	powershell -ExecutionPolicy Bypass -File scripts/demo.ps1

down:
	docker compose --profile demo down --remove-orphans

logs:
	docker compose logs -f --tail=200

smoke:
	powershell -ExecutionPolicy Bypass -File scripts/smoke_test.ps1

smoke-ps:
	powershell -ExecutionPolicy Bypass -File scripts/smoke_test.ps1


doctor:
	powershell -ExecutionPolicy Bypass -File scripts/doctor.ps1

test-docker:
	docker compose run --rm backend pytest -q

test-venv:
	python -c "import sys; assert sys.version_info[:2]==(3,11), sys.version"

# Ensure 3.11
check-py:
	python -c "import sys; assert sys.version_info[:2]==(3,11), ('use python 3.11', sys.version)"




demo:
	python -m experiments.run_live --profile diurnal --repeats 3

