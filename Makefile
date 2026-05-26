# Variables with default values (can be overridden in terminal)
SET_NAME ?= all
SERIES ?= ""
MIN_CARDS ?= 80
RARITY ?= false

.PHONY: help discover ingest clean

# 1. Help Menu - Explains how to use the tool
help:
	@echo "TCG Poke Research & ETL Tool"
	@echo "----------------------------"
	@echo "Usage examples:"
	@echo "	 make db-reset						- Drop and re-initialise database"
	@echo "  make discover                		- Show summary of all sets (Fast)"
	@echo "  make discover RARITY=True    		- Show summary with Rarity Ratio (Slower API)"
	@echo "  make discover SET_NAME=\"Silver\"    	- Research a specific set"
	@echo "  make discover SERIES='Base'  		- Filter research by series"
	@echo "  make ingest SET_NAME=\"Silver\"    	- Run ETL for a specific set"
	@echo "  make ingest                  		- Run ETL for ALL matching sets"

# Drop and re-initialize the database schema cleanly
db-reset:
	@echo "🛑 Stopping running services and clearing stale containers..."
	docker compose down
	@echo "🐘 Spinning up Postgres instance in background..."
	docker compose up -d poke_db
	@echo "⏳ Giving Postgres a moment to wake up..."
	@sleep 3
	@echo "⚠️  Dropping old views and tables cleanly..."
	@docker exec -i poke_postgres psql -U $$(grep POSTGRES_USER .env | cut -d '=' -f2) -d $$(grep POSTGRES_DB .env | cut -d '=' -f2) -c "DROP VIEW IF EXISTS meta_trends CASCADE; DROP TABLE IF EXISTS tcg_cards CASCADE; DROP TABLE IF EXISTS card_sets CASCADE;" 2> /dev/null
	@echo "🚀 Running schema initialization runner against the live database..."
	docker compose run --rm -e PGOPTIONS="-c client_min_messages=warning" dashboard python -c "from src.database.schema import initialise_poke_schemas; initialise_poke_schemas()"
	@echo "✅ Database schema reset successfully with pgvector! Ready for 'make ingest'."
	
# Audit the CLIP embedding engine classifications inside the terminal
validate:
	docker compose run --rm dashboard python -m src.ingest.run --validate

# Just show the table, no prompt, includes Rarity Ratio toggle
discover:
	python main.py --set_name "$(SET_NAME)" --series "$(SERIES)" \
	--min_cards $(MIN_CARDS) --summary_only \
	$(if $(filter True,$(RARITY)),--show_rarity,)

# Shows the table (no Rarity for speed), then asks to upload
ingest:
	python main.py --set_name "$(SET_NAME)" --series "$(SERIES)" --min_cards $(MIN_CARDS)

# Clean up python cache files
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +