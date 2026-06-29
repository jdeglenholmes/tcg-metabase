import sys
import os
import json
import logging
import requests
import argparse
from sqlalchemy import text
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Ensure project root is in path
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from src.database.connection import get_engine

# ==========================================
# 1. SETUP LOGGING
# ==========================================
os.makedirs("logs", exist_ok=True)
logger = logging.getLogger('TCG_Ingest')
logger.setLevel(logging.INFO)

# File Handler
fh = logging.FileHandler('logs/ingest_log.txt')
fh.setLevel(logging.INFO)
fh.setFormatter(logging.Formatter('[%(asctime)s] %(levelname)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
logger.addHandler(fh)

# Console Handler
ch = logging.StreamHandler(sys.stdout)
ch.setLevel(logging.INFO)
ch.setFormatter(logging.Formatter('%(message)s'))
logger.addHandler(ch)

def get_session():
    """Builds a robust requests session with retries for the TCG API."""
    session = requests.Session()
    retries = Retry(total=5, backoff_factor=1, status_forcelist=[ 429, 500, 502, 503, 504 ])
    session.mount('https://', HTTPAdapter(max_retries=retries))
    
    api_key = os.environ.get("POKEMON_TCG_API_KEY")
    if api_key:
        session.headers.update({"X-Api-Key": api_key})
    return session

def upsert_card_batch(engine, parsed_cards):
    """
    Safely inserts new cards or updates existing ones. 
    Crucially, this will NEVER overwrite existing art_style tags during an update.
    """
    if not parsed_cards:
        return 0

    query = text("""
        INSERT INTO tcg_cards (
            card_id, name, supertype, illustrator, rarity, 
            market_price, image_url, set_id, created_at, updated_at
        ) VALUES (
            :card_id, :name, :supertype, :illustrator, :rarity, 
            :market_price, :image_url, :set_id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        )
        ON CONFLICT (card_id) DO UPDATE SET
            market_price = EXCLUDED.market_price,
            image_url = EXCLUDED.image_url,
            updated_at = CURRENT_TIMESTAMP;
    """)
    
    success_count = 0
    with engine.begin() as conn:
        for card in parsed_cards:
            try:
                conn.execute(query, card)
                success_count += 1
            except Exception as e:
                logger.error(f"❌ DB Reject on {card['card_id']}: {str(e)}")
                
    return success_count

def fetch_set(set_id, engine):
    """Pulls a specific set from the API and stages it for the database."""
    session = get_session()
    page = 1
    total_parsed = []
    
    logger.info(f"📥 Beginning ingestion for set: {set_id}")
    
    while True:
        url = f"https://api.pokemontcg.io/v2/cards?q=set.id:{set_id}&page={page}&pageSize=250"
        response = session.get(url, timeout=15)
        
        if response.status_code != 200:
            logger.error(f"API Error {response.status_code}: {response.text}")
            break
            
        data = response.json().get('data', [])
        if not data:
            break
            
        for card in data:
            # Skip non-Pokemon cards right at the gate to save DB space
            supertype = card.get('supertype', '')
            if supertype != 'Pokémon':
                continue
                
            # Extract market price safely
            tcgplayer = card.get('tcgplayer', {}).get('prices', {})
            prices = tcgplayer.get('holofoil') or tcgplayer.get('normal') or {}
            market_price = prices.get('market', 0.0)
            
            parsed_card = {
                'card_id': card.get('id'),
                'name': card.get('name') or "Unknown",
                'supertype': 'Pokemon',  # Cleaned accent for DB consistency
                'illustrator': card.get('artist') or "Unknown",
                'rarity': card.get('rarity') or "Unknown",
                'market_price': market_price,
                'image_url': (card.get('images') or {}).get('large') or "",
                'set_id': set_id
            }
            total_parsed.append(parsed_card)
            
        logger.info(f"   ↳ Fetched page {page} ({len(data)} cards)")
        page += 1
        
    logger.info(f"💾 Pushing {len(total_parsed)} Pokemon cards to Supabase...")
    upsert_count = upsert_card_batch(engine, total_parsed)
    logger.info(f"🎉 Successfully saved {upsert_count} records.")

def main():
    parser = argparse.ArgumentParser(description="TCG Card API Ingestion")
    parser.add_argument('--set', type=str, help="Specific Set ID to fetch (e.g., 'sv1', 'swsh1')", required=True)
    args = parser.parse_args()
    
    engine = get_engine()
    fetch_set(args.set, engine)

if __name__ == '__main__':
    main()