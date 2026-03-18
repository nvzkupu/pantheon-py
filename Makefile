.PHONY: install dev test lint doctor secret-scan validate-skills check clean eval eval-skill eval-preview eval-init

install:
	pip install .

dev:
	pip install -e ".[dev]"

test:
	pytest tests/ -v

lint:
	ruff check src/ tests/

doctor:
	python .agents/scripts/doctor.py check

SCAN_TARGET ?= .

secret-scan:
	python .agents/scripts/secret_scan.py scan "$(SCAN_TARGET)"

validate-skills:
	python .agents/scripts/skill_validate.py validate

check: lint validate-skills test

clean:
	rm -rf build/ dist/ *.egg-info .pytest_cache __pycache__
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name '*.pyc' -delete

# --- Skillgrade evals ---

EVAL_DIRS := $(wildcard evals/*/eval.yaml)
EVAL_SKILLS := $(patsubst evals/%/eval.yaml,%,$(EVAL_DIRS))
SKILL ?=
EVAL_PATH := $(CURDIR)/evals/bin:$(PATH)

eval:
	@for skill in $(filter-out _template,$(EVAL_SKILLS)); do \
		echo "=== eval: $$skill ==="; \
		cd evals/$$skill && PATH=$(EVAL_PATH) skillgrade --smoke --provider=local && cd ../..; \
	done

eval-skill:
ifndef SKILL
	$(error SKILL is required. Usage: make eval-skill SKILL=nuwa)
endif
	cd evals/$(SKILL) && PATH=$(EVAL_PATH) skillgrade --smoke --provider=local

eval-preview:
	skillgrade preview

eval-init:
ifndef SKILL
	$(error SKILL is required. Usage: make eval-init SKILL=newskill)
endif
	@if [ -d "evals/$(SKILL)" ]; then echo "evals/$(SKILL) already exists"; exit 1; fi
	cp -r evals/_template evals/$(SKILL)
	@sed -i 's/SKILL_NAME/$(SKILL)/g' evals/$(SKILL)/eval.yaml
	@mkdir -p evals/$(SKILL)/fixtures evals/$(SKILL)/graders
	@echo "Scaffolded evals/$(SKILL)/. Next steps:"
	@echo "  1. Edit evals/$(SKILL)/eval.yaml — design tasks that test $(SKILL)'s core claim"
	@echo "  2. Add fixture files to evals/$(SKILL)/fixtures/"
	@echo "  3. Write graders in evals/$(SKILL)/graders/"
	@echo "  4. Run: make eval-skill SKILL=$(SKILL)"
