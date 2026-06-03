
SET_NAME ?= all
SERIES ?= ""
MIN_CARDS ?= 80
RARITY ?= false

# Extract DB credentials safely from .env
DB_USER := $(shell grep POSTGRES_USER .env | cut -d '=' -f2)
DB_NAME := $(shell grep POSTGRES_DB .env | cut -d '=' -f2)

DB_SERVICE := poke_db

.PHONY: help ingest enrich recompute validate

help:
	@echo "========================================================================"
	@echo "TCG DISCOVERY TOOL - DYNAMIC WORKFLOW HUB"
	@echo "========================================================================"
	@echo "Available commands:"
	@echo "  make db-reset				- Drop all tables and reset schemas."
	@echo "  make ingest SET_NAME=\"151\"		- Dynamic metadata extraction"
	@echo "  make enrich           		- Compute CLIP aesthetics for 'pending' records"
	@echo "  make recompute        		- Wipe previous evaluations and rerun CLIP models"
	@echo "  make validate         		- Run precision/recall matrix performance audit"
	@echo "========================================================================"

db-reset:
	@echo "Refreshing Database Infrastructure..."
	docker compose up -d $(DB_SERVICE)
	@sleep 3
	@echo "🧹 Cleaning tables..."
	# Dropping all tables sequentially
	docker compose exec -T $(DB_SERVICE) psql -U $(DB_USER) -d $(DB_NAME) -c \
		"DROP VIEW IF EXISTS meta_trends; \
		 DROP TABLE IF EXISTS tcg_cards CASCADE; \
		 DROP TABLE IF EXISTS vgc_stats CASCADE; \
		 DROP TABLE IF EXISTS card_sets CASCADE;"
	@echo "🚀 Applying Schema..."
	docker compose run --rm dashboard python -c \
		"from src.database.schema import initialise_poke_schemas; initialise_poke_schemas()"
	@echo "✅ Database ready."

ingest:
	@echo "Starting TCG 'Set Name > ID' resolution: $(SET_NAME)..."
	python -m src.ingest.run --ingest --set_name "$(SET_NAME)" --batch_size 20

enrich:
	python -m src.ingest.run --enrich --set_name "$(SET_NAME)" --batch_size 16

recompute:
	python -m src.ingest.run --recompute --set_name "$(SET_NAME)" --batch_size 16

validate:
	@echo "Auditing TCG set: $(SET_NAME)..."
	python -m src.ingest.run --validate --set_name "$(SET_NAME)"