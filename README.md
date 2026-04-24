## 🔍 TCGDex Research Tool
This system is a modular Python-based pipeline designed to discover Pokémon TCG metadata, analyze set distributions, and perform idempotent ingestion into a PostgreSQL database.

## 🏗️ System Architecture
The project is split into three distinct layers to ensure that research logic is decoupled from database operations.

**1. Discovery & Analysis Layer (`discovery.py`)**

This is the entry point for all external data.

* Fuzzy Search Engine: Uses Levenshtein distance via `thefuzz` to map imprecise user input to official TCG set names.

* Dynamic Filtering: Filters sets based on "Series" (e.g., _Base, Sword & Shield_) and "Minimum Card Count" to ensure only relevant competitive sets are processed.

* Rarity Profiler: Performs a sampling of the card list within a set to calculate the "Rarity Ratio," providing a percentage breakdown of Common, Rare, and Ultra-Rare cards before ingestion.

**2. Orchestration Layer (`main_3.py`)**
This file acts as the "Command Center" for the developer.

* CLI Interface: Leverages `argparse` to interpret flags passed from the Makefile.

* Stateful Branching: Distinguishes between a **Discovery Mode**(read-only research) and **Ingest Mode** (write-to-database).

* Human-in-the-loop: Enforces a mandatory `(Y/N)` confirmation prompt before triggering any heavy network or database writes.

**3. Ingestion & Persistence Layer (`etl_upload.py`)**
This is the "Worker" layer that interacts with the database (src.database.ops).

* Idempotency (The "Skip" Logic): Before downloading card details, the system queries the database to see if the `set_id` already exists. If found, it skips the set to save API quota.

* Rate Limiting: Implements a `time.sleep(0.3)` throttle to remain compliant with TCGdex API limits and prevent IP flagging.

* Atomic Upserts: Uses an `upsert` (Update or Insert) strategy to ensure that if card data is updated by the API, your database stays synchronized without creating duplicate rows.

## 🚀 Developer Workflow (Makefile)
The Makefile abstracts complex Python commands into simple, repeatable tasks.

| Command | Action |
| :--- | :--- |
| `make discover`	| Runs a global search for all sets and prints a summary table with rarity ratios. | 
| `make discover QUERY="Silver"` | Filters the summary view to sets matching "Silver". |
| `make ingest QUERY="Fossil"` | Finds the Fossil set, shows the summary, and prompts for database upload. |
| `make clean` | Removes `__pycache__` directories to keep the workspace tidy. |

## 🛠️ Logic Flow

Trigger: User executes a make command.

1. **Search:** main_3.py requests a list of sets from discovery.py using the provided filters.

2. **Analyze:** discovery.py fetches card summaries to calculate the rarity ratio.

3. **Review:** A table is printed to the terminal showing the Set Name, Card Count, and Rarity Ratio.

4. **Verify:** If in ingest mode, the user must type Y to continue.

5. **Filter:** etl_upload.py checks the local database; if the set is new, it begins the download.

6. **Persist:** Individual card details are fetched and sent to the upsert_card_data function.

## 🛑 Safety Features

* **KeyError Protection:** All API responses are accessed via .get() with defaults to prevent the script from crashing on missing data fields.

* **Automatic Schema Initialization:** The ETL pipeline calls initialise_poke_schemas() at the start of every run to ensure the database tables exist.

* **Fuzzy Threshold:** Defaulting to 80, the fuzzy search prevents low-quality matches from appearing in your results.