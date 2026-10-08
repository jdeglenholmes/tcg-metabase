import os
import sys
import time
import requests
from io import BytesIO
from PIL import Image
from tqdm import tqdm
from sqlalchemy import text
from pydantic import BaseModel, Field
from google import genai
from dotenv import load_dotenv

# Ensure project root is in path
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

load_dotenv()

from src.database.connection import get_engine
from src.database.tables import Tables

# --- INITIALIZATION ---
gemini_client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

class CameoDetectionResult(BaseModel):
    has_human: bool = Field(
        description="True if artwork explicitly shows a human, person, trainer, human silhouette, or body part. False if artwork only features monsters/Pokémon, inanimate items, energy, or landscapes."
    )
    confidence: float = Field(description="Confidence score between 0.0 and 1.0")
    reasoning: str = Field(description="Brief 1-sentence reason for judgment.")

def analyze_card_art(image_url: str, retries: int = 3) -> CameoDetectionResult:
    """Downloads image and runs Gemini 2.5 Flash Vision classification with retries."""
    for attempt in range(retries):
        try:
            resp = requests.get(image_url, timeout=10)
            if resp.status_code != 200:
                return CameoDetectionResult(has_human=False, confidence=0.0, reasoning="Failed image download")
            
            raw_image = Image.open(BytesIO(resp.content)).convert("RGB")
            prompt = (
                "Analyze this Trading Card Game artwork carefully. "
                "Determine if there is any human being, human trainer, person, human silhouette, or human body part depicted in the artwork."
            )
            
            response = gemini_client.models.generate_content(
                model='gemini-2.5-flash',
                contents=[raw_image, prompt],
                config={
                    "temperature": 0.0,
                    "response_mime_type": "application/json",
                    "response_schema": CameoDetectionResult
                }
            )
            return CameoDetectionResult.model_validate_json(response.text)
        except Exception as e:
            if attempt == retries - 1:
                return CameoDetectionResult(has_human=False, confidence=0.0, reasoning=f"Error: {str(e)}")
            time.sleep(2 ** attempt)

def update_human_cameo(engine, card_id: str, has_human: bool):
    """Updates database record with predicted human cameo value."""
    update_sql = text(f"""
        UPDATE {Tables.CARDS_CARD_DETAILS}
        SET human_cameo = :has_human,
            updated_at = CURRENT_TIMESTAMP
        WHERE card_id = :id
    """)
    with engine.begin() as conn:
        conn.execute(update_sql, {"has_human": has_human, "id": card_id})

def process_phase(engine, phase_name: str, query_sql: text):
    """Executes Gemini vision evaluation for a given batch query."""
    with engine.connect() as conn:
        cards = conn.execute(query_sql).mappings().fetchall()

    print(f"\n🚀 {phase_name}: Processing {len(cards)} cards...")
    if not cards:
        print("✅ No cards found for this phase.")
        return

    updated_count = 0
    for card in tqdm(cards, desc=phase_name, unit="card"):
        res = analyze_card_art(card['image_url'])
        update_human_cameo(engine, card['card_id'], res.has_human)
        updated_count += 1

    print(f"✅ {phase_name} Complete. Updated {updated_count} cards.")

def run_batch_classification():
    engine = get_engine()

    # --- PHASE 1: Verify 'Easy' Cards (where human_cameo is currently TRUE) ---
    phase1_query = text(f"""
        SELECT card_id, image_url 
        FROM {Tables.CARDS_CARD_DETAILS}
        WHERE supertype = 'Pokemon'
          AND image_url IS NOT NULL
          AND human_cameo IS TRUE
    """)
    process_phase(engine, "Phase 1 (Verifying human_cameo = TRUE)", phase1_query)

    # --- PHASE 2: Evaluate Cards containing 's in Name ---
    phase2_query = text(f"""
        SELECT card_id, image_url 
        FROM {Tables.CARDS_CARD_DETAILS}
        WHERE supertype = 'Pokemon'
          AND image_url IS NOT NULL
          AND name ILIKE '%''s%'
    """)
    process_phase(engine, "Phase 2 (Evaluating Trainer 's Cards)", phase2_query)

if __name__ == "__main__":
    run_batch_classification()