import argparse
import sys
import json
import logging
import requests
import os
from sqlalchemy import text
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from src.database.connection import get_engine
from src.ingest.enrichment import run_clip_enrichment_worker

# ==========================================
# 1. SETUP DUAL-LOGGING (UI + File)
# ==========================================
os.makedirs("logs", exist_ok=True)
logger = logging.getLogger('TCG_Ingest')
logger.setLevel(logging.INFO)

# File Handler (Permanent Logs)
fh = logging.FileHandler('logs/app_log.txt')
fh.setLevel(logging.INFO)
fh.setFormatter(logging.Formatter('[%(asctime)s] %(levelname)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
logger.addHandler(fh)

# Console Handler (Live Streamlit Output)
ch = logging.StreamHandler(sys.stdout)
ch.setLevel(logging.INFO)
ch.setFormatter(logging.Formatter('%(message)s'))
logger.addHandler(ch)

def check_has_trainer_art(card):
    name_lower = (card.get('name') or '').lower()
    if card.get('supertype') != 'Pokémon':
        return False
        
    known_owners = [
        "brock", "misty", "lt. surge", "erika", "koga", "sabrina", "blaine", "giovanni",
        "team rocket", "rocket", "aqua", "magma", "galactic", "plasma", "flare", "skull",
        "cynthia", "lance", "steven", "wallace", "n", "iris", "diantha", "leon",
        "geeta", "nemona", "arven", "penny", "roxanne", "brawly", "wattson", "flannery",
        "norman", "winona", "tate", "liza", "juan", "roark", "gardenia", "maylene",
        "crasher wake", "fantina", "byron", "candice", "volkner", "chili", "cress",
        "striaton", "lenora", "burgh", "elesa", "clay", "skyla", "brycen", "drayden",
        "marlon", "cheren", "roxie", "viola", "grant", "korrina", "ramos", "clemont",
        "valerie", "olympia", "wulfric", "milo", "nessa", "kabu", "bea", "allister",
        "opal", "gordie", "melony", "piers", "raihan", "marnie", "hop", "bede",
        "klara", "avery", "peony", "guzma", "lusamine", "gladion", "lillie", "hau",
        "kukui", "kris", "lyra", "ethan", "red", "blue", "green", "leaf", "hilbert",
        "hilda", "nate", "rosa", "calem", "serena", "elios", "selene", "victor",
        "gloria", "florian", "juliana", "kieran", "carmine"
    ]
    if any(f"{owner}'s" in name_lower for owner in known_owners): return True

    artist_lower = (card.get('artist') or '').lower()
    trainer_artists = [
        "sanosuke sakuma", "naoki saito", "kirisaki", "ryuta fuse", "hideki ishikawa",
        "megumi mizutani", "akira egawa", "kagemaru himeno", "sui", "kodama",
        "takeuchi", "fuzichoco", "kanako eo", "jrg", "yuu", "hncl"
    ]
    if any(artist in artist_lower for artist in trainer_artists): return True
    if "ooyama's" in name_lower or "imakuni?'s" in name_lower: return True
    return False

def fetch_cards_for_set(set_id):
    session = requests.Session()
    retries = Retry(total=5, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
    session.mount('https://', HTTPAdapter(max_retries=retries))
    
    url = "https://api.pokemontcg.io/v2/cards"
    page = 1
    all_cards = []
    
    logger.info(f"📡 Fetching API data for set: {set_id}")
    while True:
        params = {"q": f"set.id:{set_id}", "page": page, "pageSize": 250}
        try:
            response = session.get(url, params=params, timeout=20)
            response.raise_for_status()
            data = response.json()
            
            cards = data.get('data', [])
            if not cards: break
            all_cards.extend(cards)
            logger.info(f"   ↳ Downloaded page {page} ({len(cards)} cards)")
            
            if len(cards) < 250: break
            page += 1
        except Exception as e:
            logger.error(f"❌ Failed to fetch page {page}: {e}")
            break
            
    return all_cards

def upsert_card_data(conn, card_data):
    """
    CRITICAL SCHEMA FIX: 
    Postgres enforces Foreign Keys. We MUST insert the Set Metadata into `card_sets` 
    first, otherwise inserting into `tcg_cards` will trigger a hidden rollback.
    """
    set_info = card_data['set']
    
    # 1. UPSERT THE SET (Parent Table)
    query_set = text("""
        INSERT INTO card_sets (set_id, name, series, release_date, total_cards)
        VALUES (:id, :name, :series, :release_date, :total_cards)
        ON CONFLICT (set_id) DO UPDATE SET 
            name = EXCLUDED.name,
            series = EXCLUDED.series,
            release_date = EXCLUDED.release_date,
            total_cards = EXCLUDED.total_cards;
    """)
    conn.execute(query_set, {
        "id": str(set_info['id']),
        "name": str(set_info['name']),
        "series": str(set_info.get('series', 'Unknown')),
        "release_date": str(set_info.get('release_date', '0000-00-00')),
        "total_cards": int(set_info.get('total_cards') or 0)
    })

    # 2. UPSERT THE CARD (Child Table)
    query_card = text("""
        INSERT INTO tcg_cards (
            card_id, name, illustrator, rarity, set_id, 
            market_price, image_url, has_trainer, variants, supertype
        ) VALUES (
            :card_id, :name, :illustrator, :rarity, :set_id, 
            :market_price, :image_url, :has_trainer, :variants, :supertype
        )
        ON CONFLICT (card_id) DO UPDATE SET
            name = EXCLUDED.name,
            illustrator = EXCLUDED.illustrator,
            rarity = EXCLUDED.rarity,
            market_price = EXCLUDED.market_price,
            image_url = EXCLUDED.image_url,
            has_trainer = EXCLUDED.has_trainer,
            variants = EXCLUDED.variants,
            supertype = EXCLUDED.supertype;
    """)
    conn.execute(query_card, {
        "card_id": str(card_data['id']),
        "name": str(card_data['name'])[:100],
        "illustrator": str(card_data['illustrator'])[:100],
        "rarity": str(card_data['rarity'])[:50],
        "set_id": str(set_info['id']),
        "market_price": float(card_data['market_price'] or 0.0),
        "image_url": str(card_data['image_url']),
        "has_trainer": bool(card_data['is_trainer_card']),
        "variants": json.dumps(card_data['variants']),
        "supertype": str(card_data['supertype'])[:50]
    })

def main():
    parser = argparse.ArgumentParser(description="TCG ML Data Pipeline")
    parser.add_argument("--ingest", action="store_true")
    parser.add_argument("--enrich", action="store_true")
    parser.add_argument("--set_name", type=str)
    args = parser.parse_args()

    if not args.ingest and not args.enrich:
        logger.error("⚠️ Please specify an action: --ingest or --enrich")
        sys.exit(1)

    if args.enrich:
        logger.info(f"🚀 Starting Enrichment for {args.set_name}")
        run_clip_enrichment_worker(set_prefix=args.set_name)

    if args.ingest:
        if not args.set_name:
            logger.error("❌ --set_name is required for ingestion.")
            sys.exit(1)
            
        set_id = args.set_name 
        raw_cards = fetch_cards_for_set(set_id)
        
        if not raw_cards:
            logger.error(f"❌ FATAL: No cards found for set ID '{set_id}'.")
            sys.exit(1) 
            
        logger.info(f"💾 Upserting {len(raw_cards)} cards into database...")
        
        engine = get_engine()
        success_count = 0
        
        for card in raw_cards:
            try:
                tcgplayer_prices = (card.get('tcgplayer') or {}).get('prices') or {}
                market_price = None
                for price_data in tcgplayer_prices.values():
                    if price_data and price_data.get('market'):
                        market_price = price_data['market']
                        break
                        
                available_variants = tcgplayer_prices.keys()
                variants_flags = {
                    "normal": "normal" in available_variants,
                    "reverseHolofoil": "reverseHolofoil" in available_variants,
                    "holofoil": "holofoil" in available_variants,
                    "firstEdition": any("1stEdition" in v for v in available_variants)
                }
                
                # API mapping cleanly aligned to schema requirements
                parsed_card = {
                    'id': card['id'],
                    'name': card.get('name') or "Unknown",
                    'supertype': card.get('supertype') or "Unknown",
                    'is_trainer_card': check_has_trainer_art(card), 
                    'illustrator': card.get('artist') or "Unknown",
                    'rarity': card.get('rarity') or "Unknown",
                    'set': {
                        'id': card.get('set', {}).get('id', 'Unknown'),
                        'name': card.get('set', {}).get('name', 'Unknown'),
                        'series': card.get('set', {}).get('series', 'Unknown'),
                        'release_date': card.get('set', {}).get('releaseDate', '0000-00-00'),
                        'total_cards': card.get('set', {}).get('total', 0)
                    },
                    'variants': variants_flags,
                    'market_price': market_price,   
                    'image_url': (card.get('images') or {}).get('large') or "",
                }
                
                with engine.begin() as conn:
                    upsert_card_data(conn, parsed_card)
                success_count += 1
                
            except Exception as e:
                # Dumps exact schema crash to the log file!
                logger.error(f"❌ CRITICAL DATABASE REJECTION on {card.get('id', 'Unknown')}: {str(e)}")
                
        logger.info(f"🎉 Successfully upserted {success_count}/{len(raw_cards)} records.")

if __name__ == '__main__':
    main()