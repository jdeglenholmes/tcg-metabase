import os
import sys
import time
import logging
from pydantic import BaseModel
from sqlalchemy import text
from tqdm import tqdm
from dotenv import load_dotenv

# 1. Use the new SDK imports
from google import genai
from google.genai import types

# Ensure project root is in path
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
if sys.path[0] != root_dir:
    sys.path.insert(0, root_dir)

from src.database.connection import get_engine

# --- CONFIGURATION ---
load_dotenv(os.path.join(root_dir, '.env'))
logger = logging.getLogger('Dimension_Rebuild')
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(message)s')

# --- PYDANTIC SCHEMA ---
class IllustratorCategorization(BaseModel):
    style_group: str
    description: str

def rebuild_dimensions(engine):
    # 2. Initialize the new Client object
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

    with engine.connect() as conn:
        query = text("""
            SELECT DISTINCT c.illustrator 
            FROM tcg_cards c
            LEFT JOIN dim_illustrator_groups d ON c.illustrator = d.illustrator_name
            WHERE c.illustrator IS NOT NULL 
              AND c.illustrator != 'Unknown'
              AND d.illustrator_name IS NULL;
        """)
        uncategorized_artists = [row[0].strip() for row in conn.execute(query).fetchall()]

    if not uncategorized_artists:
        logger.info("✅ All illustrators are already categorized!")
        return

    logger.info(f"🎨 Sending {len(uncategorized_artists)} clean illustrators to Gemini...")

    insert_sql = text("""
        INSERT INTO dim_illustrator_groups (illustrator_name, style_group, description)
        VALUES (:name, :group, :desc)
        ON CONFLICT (illustrator_name) DO NOTHING;
    """)

    for artist in tqdm(uncategorized_artists, desc="Categorizing Artists", unit="artist"):
        prompt = f"Act as a Pokémon TCG art historian. Categorize the artist '{artist}' into their dominant visual style cohort. Provide a brief description of their aesthetic."
        
        success = False
        max_retries = 3

        for attempt in range(max_retries):
            try:
                # 3. Use the new generate_content syntax
                resp = client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.0,
                        response_mime_type="application/json",
                        response_schema=IllustratorCategorization,
                    )
                )
                
                data = IllustratorCategorization.model_validate_json(resp.text)
                
                with engine.begin() as conn:
                    conn.execute(insert_sql, {
                        "name": artist,
                        "group": data.style_group,
                        "desc": data.description
                    })
                
                time.sleep(1.5)
                success = True
                break
                
            except Exception as e:
                if "validation error" in str(e).lower() or "json" in str(e).lower():
                    logger.warning(f"⚠️ JSON error for '{artist}'. Saving fallback style.")
                    with engine.begin() as conn:
                        conn.execute(insert_sql, {
                            "name": artist,
                            "group": "Unknown Style",
                            "desc": "Automated fallback due to API parsing failure."
                        })
                    success = True
                    break
                
                if attempt == max_retries - 1:
                    logger.error(f"❌ Critical failure on '{artist}': {e}")
                    break
                
                time.sleep(10 * (2 ** attempt))

    logger.info("🎉 Dimension table rebuild complete!")

if __name__ == '__main__':
    engine = get_engine()
    rebuild_dimensions(engine)