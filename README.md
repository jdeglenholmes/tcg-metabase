## PokeNexus
This project is a modular Python-based pipeline designed to discover Pokémon TCG metadata and analyze set distributions. While it currently functions as a robust ETL tool, it is part of a wider ambition to create a streamlined application that **bridges the gap between TCG card trends and the VGC metagame**.

## System Architecture
The system is split into three distinct layers to ensure research logic is decoupled from database operations.

1. **Discovery & Analysis Layer** (`discovery.py`): Uses fuzzy search and dynamic filtering to map user input to official TCG sets. It includes a Rarity Profiler to calculate "Rarity Ratios" (Common, Rare, Ultra-Rare) before ingestion.

2. **Orchestration Layer** (`main.py`): The central command center that manages CLI arguments, stateful branching between research and ingestion modes, and human-in-the-loop confirmations.

3. **Persistence Layer** (`etl_upload.py`): Handles database interaction using idempotent "skip" logic to save API quota and rate-limiting to remain compliant with TCGdex limits.

## Developer Workflow
The `Makefile` abstracts complex Python comamnds into simple tasks.

| Command | Action |
| :--- | :--- |
| `make discover`	| Fast global search for all sets and prints a summary table. | 
| `make discover RARITY="True"` |Includes a detailed Rarity Ratio breakdown (Slower API calls). |
| `make ingest SET_NAME="Phantasmal"` | Runs the ETL pipeline for a specific set. |
| `make clean` | Removes `__pycache__` directories to keep the workspace tidy. |

## Logic Flow & Safety

Trigger: User executes a make command.

* **Search & Analyze:** The system requests sets based on filters like "Minimum Card Count" or "Series".

* **Verify:** If in ingest mode, the user must provide a mandatory (Y/N) confirmation before writing to the database.

* **Filter & Persist:** The system checks if a set_id already exists to prevent duplicates and then performs atomic upserts.

* **Error Protection:** Uses .get() defaults to prevent crashes on missing API data and includes automatic schema initialization.

## The Ambition: TCG to VGC

Currently, this tool focuses on the "Trading Card Game" side of the franchise. Future iterations aim to correlate TCG card popularity and rarity shifts with usage statistics in the VGC (Video Game Championship) metagame to identify emerging trends across both formats.