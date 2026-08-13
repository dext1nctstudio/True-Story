# =============================================================================
# TRUE STORY  ·  developer entrypoints
# =============================================================================
# Every target below runs in TRUESTORY_MODE=mock unless stated otherwise, so a
# fresh clone with no credentials can still run the full pipeline end to end.
# =============================================================================

SHELL       := /bin/bash
PY          ?= python
PIP         ?= pip
PROJECT     ?= $(shell grep -E '^GOOGLE_CLOUD_PROJECT=' .env 2>/dev/null | cut -d= -f2)
REGION      ?= us-central1
WEB_DIR     := web
DEMO_SCRIPT := demo/screenplay/the_long_shadow.fountain

.DEFAULT_GOAL := help
.PHONY: help install install-web dev dev-web mcp webhooks pipeline demo \
        test test-live lint fmt typecheck check eval eval-litigation \
        deploy-agent deploy-mcp deploy-web deploy-webhooks deploy-all \
        infra-plan infra-apply seed-cache clean

# -----------------------------------------------------------------------------
help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ── setup ────────────────────────────────────────────────────────────────────
install:  ## Install the python package with dev extras
	$(PIP) install -e ".[dev]"
	@test -f .env || cp .env.example .env
	@echo "Ready. Edit .env when you are wiring live credentials."

install-web:  ## Install the Next.js dependencies
	cd $(WEB_DIR) && npm install

# ── run ──────────────────────────────────────────────────────────────────────
dev:  ## Run the REST API and SSE stream on :8080
	TRUESTORY_MODE=mock uvicorn truestory.api.main:app --reload --port 8080

dev-web:  ## Run the verdict overlay UI on :3000
	cd $(WEB_DIR) && npm run dev

mcp:  ## Run the clearance tool server (MCP over HTTP) on :8081
	TRUESTORY_MODE=mock $(PY) -m truestory.mcp.server --port 8081

webhooks:  ## Run the signed callback receiver on :8082
	TRUESTORY_MODE=mock uvicorn truestory.webhooks.main:app --reload --port 8082

pipeline:  ## Run the ADK pipeline locally against the demo screenplay
	TRUESTORY_MODE=mock $(PY) -m truestory.cli run $(DEMO_SCRIPT) --project demo

demo:  ## Full demo path: warm cache, run, render artifacts
	TRUESTORY_MODE=cached $(PY) -m truestory.cli run $(DEMO_SCRIPT) \
		--project demo --report --open

# ── quality ──────────────────────────────────────────────────────────────────
test:  ## Unit tests, no network, no spend
	TRUESTORY_MODE=mock pytest -m "not live and not slow"

test-live:  ## Tests that hit real providers. Costs money.
	TRUESTORY_MODE=live pytest -m live

lint:  ## Ruff lint
	ruff check src tests eval

fmt:  ## Ruff format and import sort
	ruff format src tests eval
	ruff check --fix src tests eval

typecheck:  ## Mypy
	mypy src/truestory

check: lint typecheck test  ## Everything CI runs

# ── evaluation ───────────────────────────────────────────────────────────────
eval:  ## Eval A, recall and precision against the labelled demo script
	TRUESTORY_MODE=cached $(PY) eval/run_eval.py --suite labeled_script

eval-litigation:  ## Eval B, blind runs against the Litigation Set
	TRUESTORY_MODE=cached $(PY) eval/run_eval.py --suite litigation_set --blind

# ── cache ────────────────────────────────────────────────────────────────────
seed-cache:  ## One paid live run that warms the cache, every later run is free
	TRUESTORY_MODE=live $(PY) -m truestory.cli warm-cache $(DEMO_SCRIPT)

# ── deploy ───────────────────────────────────────────────────────────────────
infra-plan:  ## Terraform plan
	cd infra && terraform init && terraform plan -var="project_id=$(PROJECT)"

infra-apply:  ## Terraform apply
	cd infra && terraform apply -var="project_id=$(PROJECT)"

deploy-agent:  ## Deploy the ADK pipeline to Vertex AI Agent Engine
	$(PY) deploy/deploy_agent_engine.py --project $(PROJECT) --region $(REGION)

deploy-mcp:  ## Deploy the clearance tool server to Cloud Run
	gcloud run deploy clearance-tool-server \
		--source . --region $(REGION) --project $(PROJECT) \
		--command "python,-m,truestory.mcp.server" --concurrency 80

deploy-webhooks:  ## Deploy the callback receiver to Cloud Run
	gcloud run deploy truestory-webhooks \
		--source . --region $(REGION) --project $(PROJECT) \
		--command "uvicorn,truestory.webhooks.main:app,--host,0.0.0.0,--port,8080" \
		--min-instances 1

deploy-web:  ## Deploy the Next.js app to Cloud Run
	cd $(WEB_DIR) && gcloud run deploy truestory-web \
		--source . --region $(REGION) --project $(PROJECT) --min-instances 1

deploy-all: infra-apply deploy-agent deploy-mcp deploy-webhooks deploy-web  ## Everything

# ── housekeeping ─────────────────────────────────────────────────────────────
clean:  ## Remove build and cache artifacts
	rm -rf build dist *.egg-info .pytest_cache .ruff_cache .mypy_cache htmlcov .coverage
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
