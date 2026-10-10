import sys
import os
import logging
from sqlalchemy import text

# Ensure project root is in path
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from src.database.connection import get_engine

# ==========================================
# 1. SETUP LOGGING
# ==========================================
os.makedirs("logs", exist_ok=True)

# Force the Windows console to output in UTF-8
if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

logger = logging.getLogger('Init_Base_Tables')
logger.setLevel(logging.INFO)

# Explicitly declare utf-8 encoding for the file writer
fh = logging.FileHandler('logs/init_base_tables.txt', encoding='utf-8')
fh.setLevel(logging.INFO)
fh.setFormatter(logging.Formatter('[%(asctime)s] %(levelname)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
logger.addHandler(fh)

ch = logging.StreamHandler(sys.stdout)
ch.setLevel(logging.INFO)
ch.setFormatter(logging.Formatter('%(message)s'))
logger.addHandler(ch)

# ==========================================
# 2. SCHEMA INITIALIZATION
# ==========================================
def initialize_base_tables(engine):
    """Creates the core card_sets and tcg_cards tables if they do not exist."""
    logger.info("🛠️ Initializing base database tables (card_sets, tcg_cards)...")
    
    ddl_statements = [
        # 1. Base Table: card_sets
        """
        CREATE TABLE IF NOT EXISTS public.card_sets (
            set_id VARCHAR NOT NULL,
            name VARCHAR,
            series VARCHAR,
            release_date DATE,
            total_cards INTEGER,
            CONSTRAINT card_sets_pkey PRIMARY KEY (set_id)
        );
        """,
        # 2. Base Table: tcg_cards
        """
        CREATE TABLE IF NOT EXISTS public.tcg_cards (
            card_id VARCHAR NOT NULL,
            name VARCHAR,
            illustrator VARCHAR,
            rarity VARCHAR,
            set_id VARCHAR,
            variants JSONB,
            market_price DOUBLE PRECISION,
            created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            image_url TEXT,
            is_trainer BOOLEAN,
            -- Note: 'USER-DEFINED' replaced with TEXT. Change to 'vector(1536)' if using pgvector.
            image_embedding TEXT, 
            enrichment_status VARCHAR DEFAULT 'pending',
            tags JSONB,
            supertype VARCHAR,
            cameo_frequency INTEGER DEFAULT 0,
            cameo_pokemon JSONB,
            CONSTRAINT tcg_cards_pkey PRIMARY KEY (card_id),
            CONSTRAINT tcg_cards_set_id_fkey FOREIGN KEY (set_id) REFERENCES public.card_sets(set_id)
        );
        """
    ]

    try:
        with engine.begin() as conn:
            for stmt in ddl_statements:
                conn.execute(text(stmt))
        logger.info("✅ Base tables (card_sets and tcg_cards) initialized successfully.")
    except Exception as e:
        logger.error(f"❌ Failed to initialize base tables: {e}")

def main():
    engine = get_engine()
    initialize_base_tables(engine)

if __name__ == '__main__':
    main()