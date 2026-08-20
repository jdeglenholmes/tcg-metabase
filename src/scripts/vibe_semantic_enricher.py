import os
import sys
import time
import json
import logging
import requests
from io import BytesIO
from PIL import Image
from colorthief import ColorThief
import torch
import clip
from sqlalchemy import text
from tqdm import tqdm
from dotenv import load_dotenv
from google import genai
from pydantic import BaseModel, Field

# Ensure project root is in import path
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

env_path = os.path.join(root_dir, '.env')
load_dotenv(dotenv_path=env_path)

from src.database.connection import get_engine

# --- DUAL LOGGING SETUP ---
if sys.stdout and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

os.makedirs("logs", exist_ok=True)
logger = logging.getLogger('Holistic_Enrichment')
logger.setLevel(logging.INFO)

fh = logging.FileHandler('logs/enrichment_log.txt', encoding='utf-8')
fh.setFormatter(logging.Formatter('[%(asctime)s] %(levelname)s: %(message)s'))
logger.addHandler(fh)

class TqdmHandler(logging.Handler):
    def emit(self, record):
        tqdm.write(self.format(record))

ch = TqdmHandler()
ch.setFormatter(logging.Formatter('[%(asctime)s] %(message)s'))
logger.addHandler(ch)
logger.propagate = False

# --- CLIENT & MODEL INITIALIZATION ---
logger.info("⚙️ Initializing Local CLIP Model & Gemini Client (Illustrators Only)...")
gemini_client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

device = "cuda" if torch.cuda.is_available() else "cpu"
logger.info(f"🚀 Compute Device for CLIP Alignment: {device.upper()}")
clip_model, clip_preprocess = clip.load("ViT-B/32", device=device)
if device == "cuda":
    clip_model = clip_model.half()

# --- PYDANTIC SCHEMAS ---
class IllustratorCategorization(BaseModel):
    style_group: str = Field(
        description="Select best fit: 'Classic 90s Vintage', 'Modern Digital Manga', '3D / CGI Studio', 'Clay & Fiber Craft', 'Watercolor & Painterly', 'Abstract & Experimental'"
    )
    description: str = Field(description="Short summary of visual style.")

# --- HELPER FUNCTIONS ---
def rgb_to_hex(rgb):
    return '#{:02x}{:02x}{:02x}'.format(rgb[0], rgb[1], rgb[2])

def get_color_name(rgb):
    r, g, b = rgb
    if r > 200 and g > 200 and b > 200: return "Bright White/Light"
    if r < 50 and g < 50 and b < 50: return "Dark Shadow/Black"
    if r > g and r > b: return "Warm Red/Orange"
    if g > r and g > b: return "Lush Green"
    if b > r and b > g: return "Cool Blue"
    if r > 150 and g > 150 and b < 100: return "Vibrant Yellow/Gold"
    if r > 120 and b > 120 and g < 100: return "Mystic Purple/Pink"
    return "Muted Earth Tone"

def calculate_clip_alignment(card_name, image_bytes):
    """Calculates Cosine Similarity between 512D CLIP Text Vector and 512D CLIP Image Vector."""
    try:
        raw_image = Image.open(BytesIO(image_bytes)).convert("RGB")
        image_input = clip_preprocess(raw_image).unsqueeze(0).to(device)
        text_input = clip.tokenize([f"A Pokémon TCG card of {card_name}"]).to(device)

        with torch.no_grad():
            image_features = clip_model.encode_image(image_input)
            text_features = clip_model.encode_text(text_input)

            image_features /= image_features.norm(dim=-1, keepdim=True)
            text_features /= text_features.norm(dim=-1, keepdim=True)

            similarity = (image_features @ text_features.T).item()
            return round(float(similarity), 4)
    except Exception as e:
        logger.warning(f"CLIP alignment calculation failed: {e}")
        return None

def sync_illustrator_groups(engine, illustrators):
    """Sanitizes artists and categorizes any unknown ones using Gemini with backoff."""
    with engine.connect() as conn:
        known_artists = {
            str(row[0]).strip() 
            for row in conn.execute(text("SELECT illustrator_name FROM dim_illustrator_groups")).fetchall()
        }

    unknown_artists = [
        a.strip() for a in illustrators 
        if a and a.strip() != "Unknown" and a.strip() not in known_artists
    ]
    
    if not unknown_artists:
        logger.info("✅ All illustrators are already categorized in dim_illustrator_groups.")
        return

    logger.info(f"🎨 Categorizing {len(unknown_artists)} new illustrators...")
    insert_sql = text("""
        INSERT INTO dim_illustrator_groups (illustrator_name, style_group, description)
        VALUES (:name, :group, :desc)
        ON CONFLICT (illustrator_name) DO NOTHING;
    """)

    for artist in tqdm(unknown_artists, desc="Grouping Artists", unit="artist"):
        prompt = f"Categorize the Pokémon TCG artist '{artist}' into their dominant visual style cohort."
        max_retries = 3
        for attempt in range(max_retries):
            try:
                resp = gemini_client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=[prompt],
                    config={"temperature": 0.0, "response_mime_type": "application/json", "response_schema": IllustratorCategorization}
                )
                data = IllustratorCategorization.model_validate_json(resp.text)
                
                with engine.begin() as conn:
                    conn.execute(insert_sql, {
                        "name": artist,
                        "group": data.style_group,
                        "desc": data.description
                    })
                
                time.sleep(2)
                break
            except Exception as e:
                if attempt == max_retries - 1:
                    logger.error(f"❌ Critical Gemini failure on '{artist}': {e}. Exiting script.")
                    sys.exit(1)
                
                backoff = 15 * (2 ** attempt)
                logger.warning(f"⚠️ API Error on artist '{artist}'. Retrying in {backoff}s...")
                time.sleep(backoff)

def run_enrichment(engine):
    # 1. Sync Illustrators (Only calls Gemini if new artists exist)
    with engine.connect() as conn:
        all_artists = {row[0] for row in conn.execute(text("SELECT DISTINCT illustrator FROM tcg_cards")).fetchall()}
    sync_illustrator_groups(engine, all_artists)

    # 2. Query Unenriched Pokémon Cards Only
    # Looks for cards missing either color palette OR alignment score
    fetch_query = text("""
        SELECT card_id, name, image_url 
        FROM tcg_cards 
        WHERE REPLACE(supertype, 'é', 'e') = 'Pokemon' 
          AND (dominant_colors IS NULL OR clip_text_alignment_score IS NULL)
          AND image_url IS NOT NULL AND image_url != ''
    """)

    update_sql = text("""
        UPDATE tcg_cards 
        SET dominant_colors = :colors,
            color_vibe_description = :vibe,
            clip_text_alignment_score = :alignment
        WHERE card_id = :id
    """)

    with engine.connect() as conn:
        cards = conn.execute(fetch_query).mappings().fetchall()

    logger.info(f"⚡ Processing {len(cards)} remaining Pokémon cards (100% Local / Free Compute)...")
    if not cards:
        logger.info("✅ All Pokémon cards are fully enriched!")
        return

    for card in tqdm(cards, desc="Enriching Pokémon Cards", unit="card"):
        c_id = card['card_id']
        try:
            resp = requests.get(card['image_url'], timeout=10)
            if resp.status_code != 200:
                continue
            image_bytes = resp.content

            # A. Color Palette & Vibe Description (ColorThief - Local)
            try:
                ct = ColorThief(BytesIO(image_bytes))
                palette = ct.get_palette(color_count=3)
                hex_colors = [rgb_to_hex(c) for c in palette]
                color_names = list(set([get_color_name(c) for c in palette]))
                vibe_desc = f"Palette: {', '.join(color_names)}"
            except Exception:
                hex_colors, vibe_desc = [], "Neutral Palette"

            # B. Cross-Modal Alignment Score (CLIP - Local / CUDA)
            alignment_score = calculate_clip_alignment(card['name'], image_bytes)

            # C. Save Local Enrichment Data
            with engine.begin() as conn:
                conn.execute(update_sql, {
                    "colors": json.dumps(hex_colors),
                    "vibe": vibe_desc,
                    "alignment": alignment_score,
                    "id": c_id
                })

        except Exception as e:
            logger.error(f"❌ Failed to enrich card {c_id}: {e}")

if __name__ == '__main__':
    engine = get_engine()
    run_enrichment(engine)