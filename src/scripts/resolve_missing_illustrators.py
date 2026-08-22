import os
import sys
import re
import json
import logging
import requests
from io import BytesIO
from PIL import Image
import easyocr
import torch
from sqlalchemy import text
from tqdm import tqdm
from dotenv import load_dotenv

# Ensure project root is in path
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

env_path = os.path.join(root_dir, '.env')
load_dotenv(dotenv_path=env_path)

from src.database.connection import get_engine
# --- LOGGING SETUP ---
if sys.stdout and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

os.makedirs("logs", exist_ok=True)
logger = logging.getLogger('Illustrator_Resolver')
logger.setLevel(logging.INFO)

fh = logging.FileHandler('logs/illustrator_resolver.txt', encoding='utf-8')
fh.setFormatter(logging.Formatter('[%(asctime)s] %(levelname)s: %(message)s'))
logger.addHandler(fh)

class TqdmHandler(logging.Handler):
    def emit(self, record):
        tqdm.write(self.format(record))

ch = TqdmHandler()
ch.setFormatter(logging.Formatter('[%(asctime)s] %(message)s'))
logger.addHandler(ch)
logger.propagate = False

# --- INITIALIZE OCR ENGINE ---
use_cuda = torch.cuda.is_available()
logger.info(f"⚙️ Initializing EasyOCR Engine (CUDA Acceleration: {use_cuda})...")
ocr_reader = easyocr.Reader(['en'], gpu=False)

# REGEX Patterns for matching physical card text prints
ILLUS_PATTERNS = [
    re.compile(r"(?:Illus\.|illus\.|ILLUS\.|llus\.|lIus\.)\s*([A-Za-z0-9\s\-\.\'\+]+)", re.IGNORECASE),
    re.compile(r"art:\s*([A-Za-z0-9\s\-\.\']+)", re.IGNORECASE)
]

def extract_artist_via_ocr(image_bytes):
    """Crops the bottom 15% of the card image and extracts illustrator text using EasyOCR."""
    try:
        img = Image.open(BytesIO(image_bytes)).convert("RGB")
        w, h = img.size
        
        # Crop only the bottom banner where illustrator credit sits (bottom 15%)
        bottom_banner = img.crop((0, int(h * 0.85), w, h))
        
        # Convert PIL image to byte array for EasyOCR
        buffer = BytesIO()
        bottom_banner.save(buffer, format="JPEG")
        ocr_results = ocr_reader.readtext(buffer.getvalue(), detail=0)
        
        full_text = " ".join(ocr_results)
        
        # Check against regex patterns
        for pattern in ILLUS_PATTERNS:
            match = pattern.search(full_text)
            if match:
                raw_name = match.group(1).strip()
                # Clean up OCR noise at end of string (like set numbers or copyright symbols)
                clean_name = re.sub(r'[\d/@©®™]+.*$', '', raw_name).strip()
                if len(clean_name) > 2:
                    return clean_name
    except Exception as e:
        logger.debug(f"OCR extraction failed: {e}")
    return None

def extract_artist_via_api(card_id, session):
    """Tier 2: Direct API endpoint retry with specific headers."""
    try:
        url = f"https://api.pokemontcg.io/v2/cards/{card_id}"
        resp = session.get(url, timeout=10)
        if resp.status_code == 200:
            card_data = resp.json().get('data', {})
            artist = card_data.get('artist')
            if artist and artist.strip().lower() not in ['unknown', 'null', '']:
                return artist.strip()
    except Exception:
        pass
    return None

def extract_artist_via_web(card_name, set_id, session):
    """Tier 3: Bulbapedia / Web Search fallback parsing."""
    try:
        # Search query format targeting Bulbapedia card entry
        query = f"{card_name} {set_id} tcg bulbapedia illustrator"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        url = f"https://html.duckduckgo.com/html/?q={query}"
        
        resp = session.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            # Look for common patterns in search snippet
            match = re.search(r'illustrated by\s+([A-Za-z0-9\s\-\.\']+)', resp.text, re.IGNORECASE)
            if match:
                return match.group(1).split('.')[0].strip()
    except Exception:
        pass
    return None

def resolve_missing_illustrators(engine):
    # Fetch targeted cards only (1,045 Unknown + 23 NULL)
    fetch_sql = text("""
        SELECT card_id, name, set_id, image_url 
        FROM tcg_cards 
        WHERE illustrator IS NULL 
           OR TRIM(LOWER(illustrator)) IN ('unknown', 'null', '')
    """)

    update_sql = text("""
        UPDATE tcg_cards 
        SET illustrator = :artist 
        WHERE card_id = :card_id
    """)

    with engine.connect() as conn:
        target_cards = conn.execute(fetch_sql).mappings().fetchall()

    logger.info(f"🎯 Target Acquired: {len(target_cards)} cards missing illustrator credits.")
    if not target_cards:
        logger.info("✅ No cards requiring resolution.")
        return

    session = requests.Session()
    api_key = os.environ.get("POKEMON_TCG_API_KEY")
    if api_key:
        session.headers.update({"X-Api-Key": api_key})

    resolved_count = 0
    failed_cards = []

    for card in tqdm(target_cards, desc="Resolving Illustrators", unit="card"):
        card_id = card['card_id']
        card_name = card['name']
        image_url = card['image_url']
        found_artist = None

        # --- TIER 1: OCR Extractor (Fast & Local) ---
        if image_url:
            try:
                img_resp = session.get(image_url, timeout=10)
                if img_resp.status_code == 200:
                    found_artist = extract_artist_via_ocr(img_resp.content)
            except Exception:
                pass

        # --- TIER 2: Direct API Endpoint Fallback ---
        if not found_artist:
            found_artist = extract_artist_via_api(card_id, session)

        # --- TIER 3: Web Search Fallback ---
        if not found_artist:
            found_artist = extract_artist_via_web(card_name, card['set_id'], session)

        # --- DB UPDATE ---
        if found_artist:
            try:
                # Truncate to match schema limits
                clean_artist = str(found_artist)[:100]
                with engine.begin() as conn:
                    conn.execute(update_sql, {"artist": clean_artist, "card_id": card_id})
                resolved_count += 1
            except Exception as e:
                logger.error(f"❌ DB Update failed for {card_id}: {e}")
        else:
            failed_cards.append(card_id)

        
    logger.info(f"🎉 Successfully resolved {resolved_count}/{len(target_cards)} missing illustrators!")
    if failed_cards:
        logger.warning(f"⚠️ {len(failed_cards)} cards could not be resolved automatically: {failed_cards[:10]}...")

    # --- STEP 4: DOWNSTREAM DIMENSION SYNC ---
    if resolved_count > 0:
        logger.info("🔄 Triggering downstream sync for dim_illustrator_groups...")
        from src.scripts.vibe_semantic_enricher import sync_illustrator_groups

        with engine.connect() as conn:
            all_artists = {
                row[0] for row in conn.execute(
                    text("SELECT DISTINCT " \
                    "illustrator " \
                    "FROM tcg_cards " \
                    "WHERE illustrator IS NOT NULL AND TRIM(illustrator) != ''")
                ).fetchall()
            }
        # Uses your fortified Gemini grouping function with exponential backoff
        sync_illustrator_groups(engine, all_artists)
    
if __name__ == '__main__':
    engine = get_engine()
    resolve_missing_illustrators(engine)