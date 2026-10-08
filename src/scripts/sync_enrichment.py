import os
import sys
import logging
import requests
from sqlalchemy import text
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from src.database.connection import get_engine

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(message)s')
logger = logging.getLogger('Data_Enrichment')

def get_session():
    session = requests.Session()
    retries = Retry(total=5, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
    session.mount('https://', HTTPAdapter(max_retries=retries))
    return session

def sync_enrichment():
    engine = get_engine()
    session = get_session()
    
    # Get all sets currently in your database
    with engine.connect() as conn:
        sets = [row[0] for row in conn.execute(text("SELECT DISTINCT set_id FROM public.cards_card_details WHERE set_id IS NOT NULL")).fetchall()]
    
    # Safely update only the target columns
    update_sql = text("""
        UPDATE public.cards_card_details 
        SET market_price = :market_price,
            hp = :hp,
            types = :types,
            retreat_cost = :retreat_cost
        WHERE card_id = :card_id;
    """)

    # Use the CardDex drop-in compatibility API URL
    base_url = "https://api.carddex.dev/compat/pokemontcg/v2/cards"

    for set_id in sets:
        page = 1
        updated_count = 0
        while True:
            # We explicitly ask for specific fields to keep the payload lightweight
            url = f"{base_url}?q=set.id:{set_id}&page={page}&pageSize=250&select=id,tcgplayer,hp,types,convertedRetreatCost"
            resp = session.get(url, timeout=15)
            
            if resp.status_code != 200:
                break
                
            data = resp.json().get('data', [])
            if not data:
                break
                
            with engine.begin() as conn:
                for card in data:
                    tcgplayer = card.get('tcgplayer', {}).get('prices', {})
                    market_price = (tcgplayer.get('holofoil') or tcgplayer.get('normal') or {}).get('market', 0.0)
                    
                    # Clean HP to integer
                    try:
                        hp_val = int(card.get('hp', 0))
                    except (ValueError, TypeError):
                        hp_val = 0
                        
                    conn.execute(update_sql, {
                        'card_id': card.get('id'),
                        'market_price': float(market_price),
                        'hp': hp_val,
                        'types': card.get('types', []),
                        'retreat_cost': card.get('convertedRetreatCost', 0)
                    })
                    updated_count += 1
            page += 1
        logger.info(f"Enriched {updated_count} cards for set: {set_id}")

if __name__ == '__main__':
    sync_enrichment()