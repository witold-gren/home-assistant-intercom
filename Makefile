# home-assistant-intercom - voice messages to the rooms of the house.
#
#   make help   the steps (Polish or English, from $LANG; HELP_LANG=en|pl)

PYTHON ?= python3.13
HA_CONFIG ?= /Volumes/config
VENV := .venv
HELP_LANG ?= $(if $(filter pl%,$(LANG)),pl,en)

.DEFAULT_GOAL := help
.PHONY: help setup test test-browser test-all lint format deploy clean

##@ Start | Start

help: ## This list | Ta lista
	@awk -v lang=$(HELP_LANG) 'BEGIN { FS = ":.*## " } \
	  /^##@ / { split(substr($$0, 5), t, " \\| "); printf "\n\033[1m%s\033[0m\n", (lang == "pl" && t[2] != "") ? t[2] : t[1]; next } \
	  /^[a-zA-Z0-9_-]+:.*## / { split($$2, d, " \\| "); printf "  \033[36m%-14s\033[0m %s\n", $$1, (lang == "pl" && d[2] != "") ? d[2] : d[1] }' \
	  $(MAKEFILE_LIST)
	@echo

##@ 1. Setup | 1. Instalacja

$(VENV)/.ready: requirements_test.txt
	@echo "==> Python environment in $(VENV) ($(PYTHON))"
	@test -d $(VENV) || $(PYTHON) -m venv $(VENV)
	@$(VENV)/bin/pip install -q --upgrade pip
	@$(VENV)/bin/pip install -q -r requirements_test.txt
	@touch $@

setup: $(VENV)/.ready ## Create the environment with Home Assistant for the tests (.venv) | Utwórz środowisko z Home Assistant do testów (.venv)

##@ 2. Tests | 2. Testy

test: setup ## Tests of the integration | Testy integracji
	$(VENV)/bin/python -m pytest -q

test-browser: setup ## Tests of the card in Google Chrome | Testy karty w Google Chrome
	$(VENV)/bin/python -m pytest -q tests_browser -p no:homeassistant -p no:cacheprovider

lint: setup ## ruff: the checks and the formatting | ruff: sprawdzenie i formatowanie
	$(VENV)/bin/ruff check .
	$(VENV)/bin/ruff format --check .

format: setup ## Format the code | Sformatuj kod
	$(VENV)/bin/ruff format .
	$(VENV)/bin/ruff check --fix .

test-all: test test-browser lint ## Everything above | Wszystko powyżej

##@ 3. Home Assistant | 3. Home Assistant

deploy: ## Copy to the mounted config share (HA_CONFIG), then restart HA | Skopiuj na zamontowany udział config (HA_CONFIG), potem restart HA
	@CONFIG="$(HA_CONFIG)" ./deploy.sh

clean: ## Remove the environment and caches | Usuń środowisko i pamięci podręczne
	rm -rf $(VENV) .pytest_cache .ruff_cache
