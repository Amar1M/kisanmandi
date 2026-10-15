# KisanMandi — developer shortcuts.
# Run `make help` to see everything. If a reviewer can't get your project running
# in ten minutes, they won't. This file is how you make that possible.

.DEFAULT_GOAL := help
SHELL := /bin/bash
PY ?= python3
COMPOSE ?= docker compose

.PHONY: help install dev-install env test test-cov lint format clean \
        ingest backfill dry-run advise forecast models quality stats \
        serve verify-landing up down logs \
        tf-init tf-plan tf-apply tf-fmt tf-validate tf-destroy \
        helm-lint helm-template helm-install helm-uninstall k8s-status

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

install: ## Install runtime dependencies
	$(PY) -m pip install -e .

dev-install: ## Install with dev extras (pytest, respx, ruff)
	$(PY) -m pip install -e ".[dev]" ruff pip-audit

env: ## Create .env from the template if it doesn't exist
	@test -f .env || (cp .env.example .env && echo "created .env — now add your DATA_GOV_API_KEY")

## --- quality gates: the same commands CI runs ---------------------------------

test: ## Run the test suite
	$(PY) -m pytest -q

test-cov: ## Run tests with a coverage report
	$(PY) -m pytest -q --cov=kisanmandi --cov-report=term-missing

lint: ## Static checks (ruff)
	$(PY) -m ruff check src tests

format: ## Auto-fix lint issues
	$(PY) -m ruff check src tests --fix

audit: ## Check dependencies for known vulnerabilities
	$(PY) -m pip_audit -r requirements.txt || true

check: lint test ## Everything CI enforces, locally, in one command

## --- pipeline -----------------------------------------------------------------

env-check: ## Confirm the API key is set before you start pulling data
	@test -f .env || (echo "no .env found — run 'make env' first" && exit 1)
	@grep -q '^DATA_GOV_API_KEY=.\+' .env \
		&& echo "API key present" \
		|| (echo "WARNING: DATA_GOV_API_KEY is empty — you will be capped at 10 records/request" && exit 1)

ingest: ## Fetch today's prices (state optional: make ingest STATE=Karnataka)
	$(PY) -m kisanmandi.cli ingest $(if $(STATE),--state $(STATE),) $(if $(COMMODITY),--commodity $(COMMODITY),)

backfill: ## Pull history going backwards (DAYS=60 default). Slow on purpose.
	$(PY) -m kisanmandi.cli backfill --days $(or $(DAYS),60) $(if $(STATE),--state $(STATE),) $(if $(COMMODITY),--commodity $(COMMODITY),)

dry-run: ## Fetch and validate without writing anything — safe first run
	$(PY) -m kisanmandi.cli ingest --dry-run $(if $(STATE),--state $(STATE),)

stats: ## Row counts and effective configuration
	$(PY) -m kisanmandi.cli stats

quality: ## Regenerate the data-quality report
	$(PY) -m kisanmandi.cli quality-report $(if $(COMMODITY),--commodity $(COMMODITY),) --out docs/data-quality-report.md

verify-landing: ## Prove the raw landing zone is untampered
	$(PY) -m kisanmandi.cli verify-landing

## --- the actual product -------------------------------------------------------

advise: ## Get a recommendation: make advise COMMODITY=Tomato DISTRICT=Kolar
	$(PY) -m kisanmandi.cli advise --commodity $(or $(COMMODITY),Tomato) $(if $(DISTRICT),--district $(DISTRICT),) $(if $(MARKET),--market $(MARKET),)

forecast: ## Forecast prices: make forecast COMMODITY=Tomato MARKET=Kolar
	$(PY) -m kisanmandi.cli forecast --commodity $(or $(COMMODITY),Tomato) $(if $(MARKET),--market $(MARKET),) --horizon $(or $(HORIZON),7)

models: ## Backtest every model and rank by skill — this is your README table
	$(PY) -m kisanmandi.cli models --commodity $(or $(COMMODITY),Tomato) $(if $(DISTRICT),--district $(DISTRICT),)

serve: ## Run the API at http://localhost:8000/docs
	$(PY) -m kisanmandi.cli serve --reload

## --- containers ---------------------------------------------------------------

up: ## Start the full local stack (Postgres + API)
	$(COMPOSE) up -d
	@echo "API: http://localhost:8000/docs"

down: ## Stop the local stack and remove volumes
	$(COMPOSE) down -v

logs: ## Tail the local stack logs
	$(COMPOSE) logs -f

clean: ## Remove caches and build artefacts (does not touch data/)
	find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .ruff_cache .coverage coverage.xml htmlcov build dist *.egg-info
	find . -type f -name "*.pyc" -delete

## --- infrastructure (Oracle Cloud Always Free) ---------------------------------

tf-init: ## Initialise Terraform (downloads the OCI provider)
	cd deploy/terraform && terraform init

tf-validate: ## Check the Terraform config without touching the cloud
	cd deploy/terraform && terraform fmt -check -diff && terraform validate

tf-fmt: ## Auto-format the Terraform files
	cd deploy/terraform && terraform fmt

tf-plan: ## Preview infrastructure changes — ALWAYS read this before applying
	cd deploy/terraform && terraform plan

tf-apply: ## Create the VM (free tier, ₹0)
	@echo "Reminder: Always Free limits are 4 OCPU / 24 GB / 200 GB."
	@echo "Anything larger starts billing. Set a billing alarm first."
	cd deploy/terraform && terraform apply

tf-destroy: ## DESTROY the VM. Your data lives on the VM — read the warning first.
	@echo "This deletes the VM. Any data not backed up and not in R2 is GONE."
	@read -p "Type the word destroy to continue: " c && [ "$$c" = "destroy" ]
	cd deploy/terraform && terraform destroy

## --- kubernetes (week 7; skip until the systemd timer has run for a few nights) -

helm-lint: ## Validate the chart
	helm lint deploy/helm/kisanmandi

helm-template: ## Render the manifests locally without installing anything
	helm template kisanmandi deploy/helm/kisanmandi --namespace kisanmandi

helm-install: ## Install/upgrade into the cluster
	helm upgrade --install kisanmandi deploy/helm/kisanmandi \
		--namespace kisanmandi --create-namespace --wait

helm-uninstall: ## Remove the release (the PVC is kept — see templates/pvc.yaml)
	helm uninstall kisanmandi --namespace kisanmandi

k8s-status: ## What is running, and when did the last ingest fire?
	@kubectl -n kisanmandi get pods,cronjob 2>/dev/null || echo "no cluster / kubeconfig not set"
	@echo
	@kubectl -n kisanmandi get jobs --sort-by=.metadata.creationTimestamp 2>/dev/null | tail -5
	@echo
	@echo "Trigger an ingest manually:"
	@echo "  kubectl -n kisanmandi create job --from=cronjob/kisanmandi-ingest manual-\$$(date +%s)"

