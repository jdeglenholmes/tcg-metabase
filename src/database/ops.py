# Python/functions to push updates to poke_db

import json
from sqlalchemy import text
from src.database.connection import get_engine

def upsert_card_data(card_data: dict):
    """
    Accepts an enriched card object from TCGdex and uploads it
    into 'card_sets' and 'tcg_cards', tracking image traits and pgvector arrays.
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
            {
            'id': card_set_info.get('id'),
            'name': card_set_info.get('name'),
            'series': card_set_info.get('series')
            }
        )

        # 2. Handle the Card (child) details - Now tracking Multimodal properties
        conn.execute(
            text("""
                INSERT INTO tcg_cards (
                    card_id, name, illustrator, rarity, set_id, variants, market_price,
                    image_url, art_style, has_trainer, card_aesthetic, pokemon_count, cameo_pokemon, image_embedding
                )
                 VALUES (
                    :card_id, :name, :illustrator, :rarity, :set_id, :variants, :market_price,
                    :image_url, :art_style, :has_trainer, :card_aesthetic, :pokemon_count, :cameo_pokemon, :image_embedding
                 )
                 ON CONFLICT (card_id) DO UPDATE SET
                    market_price = EXCLUDED.market_price,
                    image_url = EXCLUDED.image_url,
                    art_style = EXCLUDED.art_style,
                    has_trainer = EXCLUDED.has_trainer,
                    card_aesthetic = EXCLUDED.card_aesthetic,
                    pokemon_count = EXCLUDED.pokemon_count,
                    cameo_pokemon = EXCLUDED.cameo_pokemon,
                    image_embedding = EXCLUDED.image_embedding,
                    updated_at = CURRENT_TIMESTAMP,
                    variants = EXCLUDED.variants;
            """),
            {
            'card_id': card_data.get('id'),
            'name': card_data.get('name'),
            'illustrator': card_data.get('illustrator'),
            'rarity': card_data.get('rarity'),
            'set_id': card_set_info.get('id'),
            # --- SAFE JSON HANDLING ---
            # Only serialize if variants exists and has keys, otherwise send true SQL None
            'variants': json.dumps(card_data['variants']) if card_data.get('variants') else None,
            'market_price': card_data.get('market_price'),
            
            # --- New Parameters for Vector & Clustering Attributes ---
            'image_url': card_data.get('image_url'),
            'art_style': card_data.get('art_style'),
            'has_trainer': card_data.get('has_trainer'),
            'card_aesthetic': card_data.get('card_aesthetic'),
            'pokemon_count': card_data.get('pokemon_count'),
            'cameo_pokemon': card_data.get('cameo_pokemon'), # Passes native Python list down to Postgres array
            'image_embedding': card_data.get('image_embedding') # Passes 512 float list straight to pgvector
            }
        )
        conn.commit()

def is_set_already_ingested(set_id):
    """Checks if we already have cards for this set in our DB."""
    engine = get_engine()
    query = text("SELECT EXISTS(SELECT 1 FROM tcg_cards WHERE set_id = :set_id);")
    with engine.connect() as conn:
        result = conn.execute(query, {"set_id": set_id}).scalar()
    return bool(result)