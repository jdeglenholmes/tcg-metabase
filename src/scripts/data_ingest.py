import os
import sys
import time
import json
import logging
import requests
from sqlalchemy import text
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from tqdm import tqdm
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer

# Ensure project root is in path
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

env_path = os.path.join(root_dir, '.env')
load_dotenv(dotenv_path=env_path)

from src.database.connection import get_engine

# ==========================================
# 1. SETUP DUAL-LOGGING (File + Console)
# ==========================================
# Force standard outputs to UTF-8 for Windows terminals
if sys.stdout and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr and sys.stderr.encoding.lower() != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')

os.makedirs("logs", exist_ok=True)
logger = logging.getLogger('TCG_Ingest')
logger.setLevel(logging.INFO)

# File Handler (Permanent Logs) - Explicitly set encoding='utf-8' here
fh = logging.FileHandler('logs/ingest_log.txt', encoding='utf-8')
fh.setLevel(logging.INFO)
fh.setFormatter(logging.Formatter('[%(asctime)s] %(levelname)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
logger.addHandler(fh)

# Custom Console Handler (Plays nicely with tqdm progress bars)
class TqdmLoggingHandler(logging.Handler):
    def emit(self, record):
        try:
            msg = self.format(record)
            tqdm.write(msg)
            self.flush()
        except Exception:
            self.handleError(record)

ch = TqdmLoggingHandler()
ch.setLevel(logging.INFO)
ch.setFormatter(logging.Formatter('[%(asctime)s] %(message)s'))
logger.addHandler(ch)
logger.propagate = False # Prevent duplicate console logs
import torch
import clip
from io import BytesIO
from PIL import Image

# ==========================================
# 2. LOCAL EMBEDDING MODELS (100% Free)
# ==========================================
logger.info("⚙️ Initializing local SentenceTransformer model (Text)...")
embedder = SentenceTransformer('all-MiniLM-L6-v2')

logger.info("👁️ Initializing local CLIP model (Vision)...")
device = "cuda" if torch.cuda.is_available() else "cpu"
logger.info(f"🚀 Vision Computation Device set to: {device.upper()}")
clip_model, clip_preprocess = clip.load("ViT-B/32", device=device)
if device == "cuda":
    clip_model = clip_model.half()

def get_session():
    session = requests.Session()
    # Increased total retries to 10 and backoff_factor to 2 for fragile upstream APIs
    retries = Retry(total=10, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504])
    session.mount('https://', HTTPAdapter(max_retries=retries))
    api_key = os.environ.get("POKEMON_TCG_API_KEY")
    if api_key:
        session.headers.update({"X-Api-Key": api_key})
    return session

def generate_embedding(card_data):
    """Generates a text embedding using local free compute."""
    text_to_embed = f"{card_data.get('name')} | {card_data.get('supertype')} | {card_data.get('artist')} | {card_data.get('rarity')}"
    try:
        # Encode locally and convert numpy array to list
        vector = embedder.encode(text_to_embed).tolist()
        return json.dumps(vector)
    except Exception as e:
        logger.warning(f"Embedding failed for {card_data.get('id')}: {e}")
        return None

def generate_image_embedding(image_url):
    """Downloads the card image and generates a 512D vision embedding."""
    if not image_url:
        return None
        
    try:
        response = requests.get(image_url, timeout=10)
        response.raise_for_status()
        raw_image = Image.open(BytesIO(response.content)).convert("RGB")
        
        image_input = clip_preprocess(raw_image).unsqueeze(0).to(device)
        with torch.no_grad():
            image_features = clip_model.encode_image(image_input)
            image_features /= image_features.norm(dim=-1, keepdim=True)
            # Convert to list for JSON serialization to Postgres
            return json.dumps(image_features[0].cpu().numpy().tolist())
            
    except Exception as e:
        logger.warning(f"Vision embedding failed for {image_url}: {e}")
        return None

def fetch_db_state(engine):
    """Retrieves known sets, cards, and the current count of cards per set."""
    with engine.connect() as conn:
        known_sets = {row[0] for row in conn.execute(text("SELECT set_id FROM card_sets")).fetchall()}
        known_cards = {row[0] for row in conn.execute(text("SELECT card_id FROM tcg_cards")).fetchall()}
        
        # NEW: Count how many cards we currently have for each set
        set_counts = {
            row[0]: row[1] 
            for row in conn.execute(text("SELECT set_id, COUNT(card_id) FROM tcg_cards GROUP BY set_id")).fetchall()
        }
        
    return known_sets, known_cards, set_counts

def sync_missing_data(engine):
    session = get_session()
    known_sets, known_cards, set_counts = fetch_db_state(engine) # Destructure the new set_counts
    
    tcg_key = os.environ.get("POKEMON_TCG_API_KEY")
    delay = 0.2 if tcg_key else 1.0
    
    # 1. Sync Sets
    logger.info("📦 Fetching master set list from API...")
    try:
        sets_response = session.get("https://api.pokemontcg.io/v2/sets", timeout=15).json().get('data', [])
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Failed to fetch set list: {e}")
        return
    
    missing_sets = [s for s in sets_response if s['id'] not in known_sets]
    if missing_sets:
        logger.info(f"📥 Found {len(missing_sets)} missing sets. Upserting...")
        set_sql = text("""
            INSERT INTO card_sets (set_id, name, series, release_date, total_cards)
            VALUES (:id, :name, :series, CAST(:release_date AS DATE), :total_cards)
            ON CONFLICT (set_id) DO NOTHING;
        """)
        with engine.begin() as conn:
            for s in tqdm(missing_sets, desc="Inserting Missing Sets", unit="set"):
                conn.execute(set_sql, {
                    "id": str(s.get('id')),
                    "name": str(s.get('name')),
                    "series": str(s.get('series') or 'Unknown')[:100],
                    "release_date": str(s.get('releaseDate') or '0000-00-00'),
                    "total_cards": int(s.get('total') or 0)
                })
    else:
        logger.info("✅ All sets are up to date.")

    # 2. Smart Delta Check (Find sets needing updates)
    logger.info(f"🧮 Calculating Delta: Pre-scanning API for missing cards (Throttle: {delay}s/req)...")
    sets_to_update = []
    
    for s in tqdm(sets_response, desc="Checking Set Totals", unit="set"):
        set_id = s['id']
        time.sleep(delay)
        
        # Lightweight ping: Request only 1 ID to force the API to return the totalCount of Pokemon cards
        url = f"https://api.pokemontcg.io/v2/cards?q=set.id:{set_id} supertype:pokemon&pageSize=1&select=id"
        
        try:
            resp = session.get(url, timeout=10)
            if resp.status_code != 200:
                logger.warning(f"⚠️ HTTP {resp.status_code} on set '{set_id}'. Forcing update just in case.")
                sets_to_update.append(s)
                continue
            
            api_total = resp.json().get('totalCount', 0)
            db_total = set_counts.get(set_id, 0)
            
            # If the database has fewer cards than the API reports, flag it for updating
            if db_total < api_total:
                sets_to_update.append(s)
                
        except requests.exceptions.RequestException as e:
            logger.warning(f"❌ Delta check failed on '{set_id}': {e}. Forcing update.")
            sets_to_update.append(s)

    if not sets_to_update:
        logger.info("✅ All Pokemon cards across all sets are fully up to date!")
        return

    # 3. Sync Missing Cards
    logger.info(f"📥 Found {len(sets_to_update)} sets requiring updates. Beginning ingestion...")
    card_sql = text("""
        INSERT INTO tcg_cards (
            card_id, name, supertype, illustrator, rarity, 
            market_price, image_url, set_id, text_embedding, image_embedding
        ) VALUES (
            :card_id, :name, :supertype, :illustrator, :rarity, 
            :market_price, :image_url, :set_id, :text_embedding, :image_embedding
        )
        ON CONFLICT (card_id) DO NOTHING;
    """)

    # This progress bar will now ONLY reflect the sets that actually failed or are missing data!
    for s in tqdm(sets_to_update, desc="Syncing Missing Cards", unit="set"):
        set_id = s['id']
        page = 1
        while True:
            time.sleep(delay)
            # Optimized Query: Explicitly asks only for Pokemon to reduce JSON payload size
            url = f"https://api.pokemontcg.io/v2/cards?q=set.id:{set_id} supertype:pokemon&page={page}&pageSize=50"
            
            try:
                resp = session.get(url, timeout=15)
                if resp.status_code != 200:
                    logger.warning(f"⚠️ HTTP {resp.status_code} on set '{set_id}' page {page}. Moving to next set.")
                    break
                data = resp.json().get('data', [])
            except requests.exceptions.RequestException as e:
                logger.error(f"❌ Request failed on set '{set_id}' page {page}: {e}")
                break

            if not data:
                break
                
            missing_cards = [c for c in data if c['id'] not in known_cards]
            
            if missing_cards:
                logger.info(f"   ↳ Ingesting {len(missing_cards)} missing cards from set '{set_id}' (Page {page})...")
                for card in missing_cards:
                    try:
                        prices = (card.get('tcgplayer', {}).get('prices', {}).get('holofoil') or 
                                  card.get('tcgplayer', {}).get('prices', {}).get('normal') or {})
                        
                        raw_supertype = str(card.get('supertype') or "Unknown")
                        clean_supertype = raw_supertype.replace('é', 'e').replace('É', 'E')
                        image_url = str((card.get('images') or {}).get('large') or "")
                        
                        payload = {
                            'card_id': str(card.get('id')),
                            'name': str(card.get('name') or "Unknown")[:100],
                            'supertype': clean_supertype[:50],
                            'illustrator': str(card.get('artist') or "Unknown")[:100],
                            'rarity': str(card.get('rarity') or "Unknown")[:50],
                            'market_price': float(prices.get('market') or 0.0),
                            'image_url': image_url,
                            'set_id': str(set_id),
                            'text_embedding': generate_embedding(card),
                            'image_embedding': generate_image_embedding(image_url)
                        }
                        
                        with engine.begin() as conn:
                            conn.execute(card_sql, payload)
                            
                        known_cards.add(card['id'])
                    except Exception as e:
                        logger.error(f"❌ DB Rejection on {card.get('id')}: {e}")
            page += 1

if __name__ == '__main__':
    tcg_key = os.environ.get("POKEMON_TCG_API_KEY")
    logger.info(f"🔑 POKEMON_TCG_API_KEY: {'LOADED (250 req/min)' if tcg_key else 'NOT PRESENT (Using 60 req/min throttling)'}")
    
    engine = get_engine()
    sync_missing_data(engine)