import sys
import os
import json
import logging
import requests
import argparse
from sqlalchemy import text
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Ensure project root is in system path
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from src.database.connection import get_engine

# ==========================================
# 1. SETUP LOGGING
# ==========================================
os.makedirs("logs", exist_ok=True)

# FIX 1: Force the Windows console to output in UTF-8
if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

logger = logging.getLogger('Pokemon_Mart_Pipeline')
logger.setLevel(logging.INFO)

# FIX 2: Explicitly declare utf-8 encoding for the file writer
fh = logging.FileHandler('logs/pokemon_mart_pipeline.txt', encoding='utf-8')
fh.setLevel(logging.INFO)
fh.setFormatter(logging.Formatter('[%(asctime)s] %(levelname)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
logger.addHandler(fh)

# Console Handler
ch = logging.StreamHandler(sys.stdout)
ch.setLevel(logging.INFO)
ch.setFormatter(logging.Formatter('%(message)s'))
logger.addHandler(ch)

# ==========================================
# 2. HTTP SESSION SETUP
# ==========================================
def get_session():
    """Builds a robust requests session with retries for external APIs."""
    session = requests.Session()
    retries = Retry(total=5, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
    session.mount('https://', HTTPAdapter(max_retries=retries))
    return session

# ==========================================
# 3. SCHEMA & MART INITIALIZATION
# ==========================================
def initialize_schema_and_marts(engine):
    """Creates the dimension, bridge, and gold mart views in PostgreSQL if they don't exist."""
    logger.info("🛠️ Initializing database tables, constraints, and views...")
    
    ddl_statements = [
        # 1. Dimension Table: dim_pokemon
        """
        CREATE TABLE IF NOT EXISTS public.dim_pokemon (
            pokemon_id SERIAL PRIMARY KEY,
            pokedex_number INTEGER UNIQUE,
            pokemon_name VARCHAR(255) UNIQUE NOT NULL,
            created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
        );
        """,
        # 2. Fact / Bridge Table: fact_card_appearances
        """
        CREATE TABLE IF NOT EXISTS public.fact_card_appearances (
            appearance_id SERIAL PRIMARY KEY,
            card_id VARCHAR(255) NOT NULL REFERENCES public.tcg_cards(card_id) ON DELETE CASCADE,
            pokemon_id INTEGER NOT NULL REFERENCES public.dim_pokemon(pokemon_id) ON DELETE CASCADE,
            is_primary_subject BOOLEAN DEFAULT FALSE,
            is_cameo BOOLEAN DEFAULT FALSE,
            CONSTRAINT unique_card_pokemon UNIQUE (card_id, pokemon_id)
        );
        """,
        # 3. Gold Analytical Mart View: mart_pokemon_metrics
        """
        CREATE OR REPLACE VIEW public.mart_pokemon_metrics AS
        WITH partner_encounters AS (
            SELECT 
                f1.pokemon_id AS base_pokemon_id,
                f2.pokemon_id AS partner_pokemon_id,
                COUNT(f1.card_id) AS encounter_count
            FROM public.fact_card_appearances f1
            JOIN public.fact_card_appearances f2 
                ON f1.card_id = f2.card_id 
                AND f1.pokemon_id != f2.pokemon_id
            GROUP BY f1.pokemon_id, f2.pokemon_id
        ),
        ranked_partners AS (
            SELECT 
                base_pokemon_id,
                partner_pokemon_id,
                encounter_count,
                ROW_NUMBER() OVER(PARTITION BY base_pokemon_id ORDER BY encounter_count DESC) AS rank
            FROM partner_encounters
        )
        SELECT 
            p.pokemon_id,
            p.pokedex_number,
            p.pokemon_name,
            COUNT(DISTINCT f.card_id) AS total_cards_featured,
            COUNT(DISTINCT f.card_id) FILTER (WHERE f.is_primary_subject = TRUE) AS primary_cards,
            COUNT(DISTINCT f.card_id) FILTER (WHERE f.is_cameo = TRUE) AS cameo_appearances,
            ROUND(AVG(c.market_price)::numeric, 2) AS avg_market_price,
            MAX(c.market_price) AS max_market_price,
            partner.pokemon_name AS top_partner_name,
            COALESCE(rp.encounter_count, 0) AS top_partner_encounters
        FROM public.dim_pokemon p
        LEFT JOIN public.fact_card_appearances f ON p.pokemon_id = f.pokemon_id
        LEFT JOIN public.tcg_cards c ON f.card_id = c.card_id
        LEFT JOIN ranked_partners rp ON p.pokemon_id = rp.base_pokemon_id AND rp.rank = 1
        LEFT JOIN public.dim_pokemon partner ON rp.partner_pokemon_id = partner.pokemon_id
        GROUP BY 
            p.pokemon_id, 
            p.pokedex_number,
            p.pokemon_name, 
            partner.pokemon_name, 
            rp.encounter_count;
        """
    ]

    with engine.begin() as conn:
        for stmt in ddl_statements:
            conn.execute(text(stmt))
            
    logger.info("✅ Schema, bridge tables, and gold mart view initialized successfully.")

# ==========================================
# 4. POKEAPI INGESTION
# ==========================================
def fetch_and_seed_pokeapi(engine):
    """Fetches all official Pokémon species from PokéAPI and seeds dim_pokemon."""
    session = get_session()
    url = "https://pokeapi.co/api/v2/pokemon?limit=2000"
    
    logger.info("🌐 Querying PokéAPI (https://pokeapi.co/api/v2/pokemon)...")
    response = session.get(url, timeout=30)
    
    if response.status_code != 200:
        logger.error(f"❌ Failed PokéAPI fetch: HTTP {response.status_code}")
        return

    results = response.json().get('results', [])
    logger.info(f"📦 Retrieved {len(results)} records from PokéAPI. Processing into dim_pokemon...")

    upsert_sql = text("""
        INSERT INTO public.dim_pokemon (pokedex_number, pokemon_name)
        VALUES (:pokedex_number, :pokemon_name)
        ON CONFLICT (pokemon_name) DO UPDATE SET
            pokedex_number = EXCLUDED.pokedex_number;
    """)

    records_saved = 0
    with engine.begin() as conn:
        for entry in results:
            raw_name = entry.get('name', '')
            url_parts = entry.get('url', '').strip('/').split('/')
            
            if not raw_name or not url_parts[-1].isdigit():
                continue

            pokedex_num = int(url_parts[-1])
            formatted_name = raw_name.replace('-', ' ').title()

            conn.execute(upsert_sql, {
                "pokedex_number": pokedex_num,
                "pokemon_name": formatted_name
            })
            records_saved += 1

    logger.info(f"🎉 Successfully seeded/updated {records_saved} official Pokémon in dim_pokemon.")

# ==========================================
# 5. BRIDGE TABLE & MART POPULATION
# ==========================================
def populate_fact_appearances(engine):
    """
    Parses tcg_cards (both primary card names and JSON cameo_pokemon arrays)
    and updates fact_card_appearances to power the gold mart.
    """
    logger.info("🔄 Syncing tcg_cards data into fact_card_appearances...")

    # Step A: Seed any custom or unlisted card subject names into dim_pokemon
    seed_primary_names_sql = text("""
        INSERT INTO public.dim_pokemon (pokemon_name)
        SELECT DISTINCT INITCAP(TRIM(name))
        FROM public.tcg_cards
        WHERE name IS NOT NULL AND TRIM(name) != ''
        ON CONFLICT (pokemon_name) DO NOTHING;
    """)

    seed_cameo_names_sql = text("""
        INSERT INTO public.dim_pokemon (pokemon_name)
        SELECT DISTINCT INITCAP(TRIM(json_array_elements_text(cameo_pokemon::json)))
        FROM public.tcg_cards
        WHERE cameo_pokemon IS NOT NULL 
          AND cameo_pokemon::text NOT IN ('null', '[]', '')
        ON CONFLICT (pokemon_name) DO NOTHING;
    """)

    # Step B: Populate primary subject card appearances
    insert_primary_appearances_sql = text("""
        INSERT INTO public.fact_card_appearances (card_id, pokemon_id, is_primary_subject, is_cameo)
        SELECT c.card_id, p.pokemon_id, TRUE, FALSE
        FROM public.tcg_cards c
        JOIN public.dim_pokemon p ON LOWER(TRIM(c.name)) = LOWER(p.pokemon_name)
        ON CONFLICT (card_id, pokemon_id) 
        DO UPDATE SET is_primary_subject = EXCLUDED.is_primary_subject;
    """)

    # Step C: Populate cameo card appearances
    insert_cameo_appearances_sql = text("""
        INSERT INTO public.fact_card_appearances (card_id, pokemon_id, is_primary_subject, is_cameo)
        SELECT c.card_id, p.pokemon_id, FALSE, TRUE
        FROM public.tcg_cards c
        CROSS JOIN LATERAL json_array_elements_text(c.cameo_pokemon::json) AS cameo_name
        JOIN public.dim_pokemon p ON LOWER(TRIM(cameo_name)) = LOWER(p.pokemon_name)
        WHERE c.cameo_pokemon IS NOT NULL 
          AND c.cameo_pokemon::text NOT IN ('null', '[]', '')
        ON CONFLICT (card_id, pokemon_id) 
        DO UPDATE SET is_cameo = TRUE;
    """)

    with engine.begin() as conn:
        logger.info("  ↳ Extracting unique entity names from tcg_cards...")
        conn.execute(seed_primary_names_sql)
        try:
            conn.execute(seed_cameo_names_sql)
        except Exception as e:
            logger.warning(f"  ⚠️ Cameo JSON parsing skipped or empty: {e}")

        logger.info("  ↳ Linking primary subjects in fact_card_appearances...")
        conn.execute(insert_primary_appearances_sql)

        logger.info("  ↳ Linking cameo appearances in fact_card_appearances...")
        try:
            conn.execute(insert_cameo_appearances_sql)
        except Exception as e:
            logger.warning(f"  ⚠️ Cameo linkage skipped or empty: {e}")

    logger.info("🚀 Fact appearances synchronized! The mart_pokemon_metrics view is up to date.")

# ==========================================
# 6. MAIN PIPELINE EXECUTION
# ==========================================
def main():
    parser = argparse.ArgumentParser(description="Master Pokémon Data Mart & PokéAPI Pipeline")
    parser.add_argument('--skip-pokeapi', action='store_true', help="Skip fetching from PokéAPI and only sync local DB tables.")
    args = parser.parse_args()

    engine = get_engine()

    # Step 1: Ensure all schemas, tables, and views exist
    initialize_schema_and_marts(engine)

    # Step 2: Fetch official National Dex Pokémon metadata from PokéAPI
    if not args.skip_pokeapi:
        fetch_and_seed_pokeapi(engine)

    # Step 3: Populate bridge relationships and refresh the analytics mart
    populate_fact_appearances(engine)

if __name__ == '__main__':
    main()