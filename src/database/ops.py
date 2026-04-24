#Python/functions to push updates to poke_db

import json
from sqlalchemy import text
from src.database.connection import get_engine

def upsert_card_data(card_data: dict):
    """
    Accepts a card object from TCGdex and uploads it
    into 'card_sets' and 'tcg_cards'.
    """
    engine = get_engine()

    with engine.connect() as conn:
        # 1. Handle the Card Set (parent) details that each card belongs to
        card_set_info = card_data.get('set', {})
        
        # note: card_sets must be updated first due to foreign key constraints
        conn.execute(
            text("""
                INSERT INTO card_sets (set_id, name, series)
                 VALUES (:id, :name, :series)
                 ON CONFLICT (set_id) DO NOTHING; -- Do not upsert if set already exists
            """),
        # Pass engine key-value pairs based on card_set_info
            {
            'id': card_set_info.get('id'),
            'name': card_set_info.get('name'),
            'series': card_set_info.get('series')
            }
        )

        # 2. Handle the Card (child) details
        conn.execute(
            text("""
                INSERT INTO tcg_cards (card_id, name, illustrator, rarity, set_id, variants)
                 VALUES (:card_id, :name, :illustrator, :rarity, :set_id, :variants)
                 ON CONFLICT (card_id) DO UPDATE SET
                    -- If card already exists, continue to update time and variant JSON 
                    updated_at = CURRENT_TIMESTAMP,
                    variants = EXCLUDED.variants;
            """),
        # Pass engine key-value pairs based on card_data
            {
            'card_id': card_data.get('id'),
            'name': card_data.get('name'),
            'illustrator': card_data.get('illustrator'),
            'rarity': card_data.get('rarity'),
            'set_id': card_set_info.get('id'), # Accessed using card_set_info
            'variants': json.dumps(card_data.get('variants', {}))
            }

        )
        conn.commit()

def is_set_already_ingested(set_id):
    """Checks if we already have cards for this set in our DB."""
    query = "SELECT EXISTS(SELECT 1 FROM tcg_cards WHERE set_id = :set_id)"
    # Logic: If even 1 card exists for this set_id, we consider it 'ingested'
    # Return True or False based on the SQL result