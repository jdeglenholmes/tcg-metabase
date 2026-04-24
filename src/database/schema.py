#Python/defines schemas for sets, cards and video game series

from sqlalchemy import text
from src.database.connection import get_engine

def initialise_poke_schemas():
    engine = get_engine() # Save connection blueprints to engine obj

    # Three distinct SQL queries for granular error handling
    sql_queries = [
    # 1. Card Sets Table: trends across different tcg releases
    """
    CREATE TABLE IF NOT EXISTS card_sets (
        set_id VARCHAR(50) PRIMARY KEY,
        name VARCHAR(100),
        series VARCHAR(100),
        release_date DATE,
        total_cards INT
    );
    """,
    # 2. Card Object Table: granular card detail
   """
    CREATE TABLE IF NOT EXISTS tcg_cards (
        card_id VARCHAR(50) PRIMARY KEY,
        name VARCHAR(100),
        illustrator VARCHAR(100),
        rarity VARCHAR(50),
        set_id VARCHAR(50) REFERENCES card_sets(set_id),
        variants JSONB,  -- Stores holo/normal/first-edition flags
        market_price FLOAT,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """,
    # 3. VGC Pokemon Stats Table: usage data for each pokemon
    """
    CREATE TABLE IF NOT EXISTS vgc_stats (
        pokemon_name VARCHAR(100) PRIMARY KEY,
        usage_percent FLOAT,
        rank INT,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """,
    # 4. Combined View Table: centralised 'truth' of all three tables
    """
    CREATE OR REPLACE VIEW meta_trends AS
        SELECT
            tcg.name as card_name,
            tcg.illustrator as card_illustrator,
            tcg.rarity as card_rarity,
            tcg.variants as card_variants,
            tcg_set.name as set_name,
            tcg_set.release_date as set_release_date,
            tcg.market_price as card_price,
            vgc.usage_percent as vgc_usage_percent,
            vgc.rank as vgc_rank
        FROM 
            tcg_cards tcg
        JOIN 
            card_sets tcg_set ON tcg.set_id = tcg_set.set_id
        LEFT JOIN 
            vgc_stats vgc ON tcg.name = vgc.pokemon_name
        ;
    """
    ]

    with engine.connect() as conn:
        for query in sql_queries:
            conn.execute(text(query))
            conn.commit()
    print("✅ Pokémon SQL tables initialized!")