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
	@echo "  make discover                		- Show summary of all sets (Fast)"
	@echo "  make discover RARITY=True    		- Show summary with Rarity Ratio (Slower API)"
	@echo "  make discover SET_NAME=\"Silver\"    	- Research a specific set"
	@echo "  make discover SERIES='Base'  		- Filter research by series"
	@echo "  make ingest SET_NAME=\"Silver\"    	- Run ETL for a specific set"
	@echo "  make ingest                  		- Run ETL for ALL matching sets"

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