import json
from sqlalchemy import text
from src.database.connection import get_engine

def upsert_card_data(card_data: dict):
    """
    Refactored for dynamic metadata: Upserts set info first, 
    then updates/inserts card records safely preserving ML data.
    """
    engine = get_engine()
    card_set_info = card_data.get('set', {})

    with engine.begin() as conn: # using engine.begin() automatically handles the commit!
        # 1. UPSERT Set Metadata (Parent)
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
                    image_url, art_style, has_trainer, card_aesthetic, cameos, image_embedding
                )
                VALUES (
                    :card_id, :name, :illustrator, :rarity, :set_id, :variants, :market_price,
                    :image_url, :art_style, :has_trainer, :card_aesthetic, :cameos, :image_embedding
                )
                ON CONFLICT (card_id) DO UPDATE SET
                    market_price = EXCLUDED.market_price,
                    image_url = EXCLUDED.image_url,
                    variants = EXCLUDED.variants,
                    has_trainer = EXCLUDED.has_trainer,
                    
                    -- ML SAFEGUARDS: Do not overwrite existing ML data with NULLs during re-ingestion
                    art_style = COALESCE(EXCLUDED.art_style, tcg_cards.art_style),
                    card_aesthetic = COALESCE(EXCLUDED.card_aesthetic, tcg_cards.card_aesthetic),
                    cameos = COALESCE(EXCLUDED.cameos, tcg_cards.cameos),
                    image_embedding = COALESCE(EXCLUDED.image_embedding, tcg_cards.image_embedding),
                    
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
                
                # safely map the 'is_trainer_card' dictionary key to the 'has_trainer' db column
                'has_trainer': card_data.get('is_trainer_card', False), 
                
                # ML Columns (Likely None during initial API ingest, populated later by enrichment.py)
                'art_style': json.dumps(card_data.get('art_style')) if card_data.get('art_style') else None,
                'card_aesthetic': json.dumps(card_data.get('card_aesthetic')) if card_data.get('card_aesthetic') else None,
                'cameos': card_data.get('cameos'),
                'image_embedding': card_data.get('image_embedding')
            }
        )