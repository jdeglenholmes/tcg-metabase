import json
from sqlalchemy import text
from src.database.connection import get_engine

def upsert_card_data(card_data: dict):
    """
    Refactored for dynamic metadata: Upserts set info first, 
    then updates/inserts card records.
    """
    engine = get_engine()
    card_set_info = card_data.get('set', {})

    with engine.connect() as conn:
        # 1. UPSERT Set Metadata (Parent)
        # Keeps name, series, date, and total_cards synced with the API
        conn.execute(
            text("""
                INSERT INTO card_sets (set_id, name, series, release_date, total_cards)
                VALUES (:id, :name, :series, :release_date, :total_cards)
                ON CONFLICT (set_id) DO UPDATE SET 
                    name = EXCLUDED.name,
                    series = EXCLUDED.series,
                    release_date = COALESCE(EXCLUDED.release_date, card_sets.release_date),
                    total_cards = COALESCE(EXCLUDED.total_cards, card_sets.total_cards);
            """),
            {
                'id': card_set_info.get('id'),
                'name': card_set_info.get('name'),
                'series': card_set_info.get('series'),
                'release_date': card_set_info.get('release_date'),
                'total_cards': card_set_info.get('total_cards')
            }
        )

        # 2. UPSERT Card Details (Child)
        conn.execute(
            text("""
                INSERT INTO tcg_cards (
                    card_id, name, illustrator, rarity, set_id, variants, market_price,
                    image_url, art_style, has_trainer, card_aesthetic, pokemon_count, 
                    cameo_pokemon, image_embedding
                )
                VALUES (
                    :card_id, :name, :illustrator, :rarity, :set_id, :variants, :market_price,
                    :image_url, :art_style, :has_trainer, :card_aesthetic, :pokemon_count, 
                    :cameo_pokemon, :image_embedding
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
                    variants = EXCLUDED.variants,
                    updated_at = CURRENT_TIMESTAMP;
            """),
            {
                'card_id': card_data.get('id'),
                'name': card_data.get('name'),
                'illustrator': card_data.get('illustrator'),
                'rarity': card_data.get('rarity'),
                'set_id': card_set_info.get('id'),
                'variants': json.dumps(card_data['variants']) if card_data.get('variants') else None,
                'market_price': card_data.get('market_price'),
                'image_url': card_data.get('image_url'),
                'art_style': card_data.get('art_style'),
                'has_trainer': card_data.get('has_trainer'),
                'card_aesthetic': card_data.get('card_aesthetic'),
                'pokemon_count': card_data.get('pokemon_count'),
                'cameo_pokemon': card_data.get('cameo_pokemon'),
                'image_embedding': card_data.get('image_embedding')
            }
        )
        conn.commit()