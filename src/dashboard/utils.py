import os
import json
import requests
from io import BytesIO
from PIL import Image
import streamlit as st
from sqlalchemy import text
from pydantic import BaseModel, Field
from google import genai
from src.database.tables import Tables
from src.database.connection import get_engine as get_base_engine

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))

# --- GEMINI CLIENT INITIALIZATION ---
gemini_client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

# --- PYDANTIC SCHEMA FOR GEMINI MULTIMODAL DETECTION ---
class CameoDetectionResult(BaseModel):
    has_human: bool = Field(
        description="True if artwork explicitly shows a human, person, trainer, human silhouette, or body part. False if artwork only features monsters/Pokémon, inanimate items, energy, or landscapes."
    )
    confidence: float = Field(description="Confidence score between 0.0 and 1.0")
    reasoning: str = Field(description="Brief 1-sentence reason for judgment.")

# --- GEMINI VISION INFERENCE HELPER ---
def analyze_image_for_human(image_url: str) -> CameoDetectionResult:
    """Downloads card image and passes bytes directly to Gemini 2.5 Flash Vision."""
    try:
        resp = requests.get(image_url, timeout=8)
        if resp.status_code != 200:
            return CameoDetectionResult(has_human=False, confidence=0.0, reasoning="Image fetch failed.")
        
        raw_image = Image.open(BytesIO(resp.content)).convert("RGB")
        
        prompt = (
            "Analyze this Trading Card Game artwork carefully. "
            "Determine if there is any human being, human trainer, person, human silhouette, or human cameo depicted in the artwork."
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
        return CameoDetectionResult(has_human=False, confidence=0.0, reasoning=f"Gemini API Error: {str(e)}")

# --- UPDATED CAMEO GUESSES FETCH FUNCTION ---
def fetch_cameo_guesses(engine, limit: int):
    """
    Fetches cards where human_cameo IS NULL, evaluates artwork live via Gemini 2.5 Flash,
    and attaches model predictions & reasoning for rapid UI verification.
    """
    base_query = text(f"""
        SELECT 
            c.card_id,
            (SPLIT_PART(c.card_id, '-', 2) || '/' || s.total_cards::text) as position_id,
            c.name, c.illustrator, c.rarity, c.market_price, c.image_url, 
            COALESCE(c.rotation_angle, 0) AS rotation_angle,
            c.is_trainer, c.human_cameo, c.is_shiny, c.cameo_frequency, c.cameo_pokemon,
            s.name AS set_name,
            p.grid_group_name AS phys_group, p.grid_width, p.grid_height, p.position_x, p.position_y,
            n.story_name, n.sequence_order, n.narrative_role
        FROM {Tables.CARDS_CARD_DETAILS} c
        LEFT JOIN {Tables.CARDS_SET_DETAILS} s ON c.set_id = s.set_id
        LEFT JOIN {Tables.CARDS_CARD_STORY_GRID_DIMENSIONS} p ON c.card_id = p.card_id
        LEFT JOIN {Tables.CARDS_CARD_CONNECTING_GRID_DIMENSIONS} n ON c.card_id = n.card_id
        WHERE c.supertype != 'Item' 
          AND c.image_url IS NOT NULL 
          AND c.human_cameo IS NOT NULL
        ORDER BY RANDOM() 
        LIMIT :limit
    """)
    
    with engine.connect() as conn:
        results = conn.execute(base_query, {"limit": limit}).mappings().fetchall()
        cards = [dict(c) for c in results]

    # Run Gemini multimodal vision evaluation across fetched cards
    for card in cards:
        eval_res = analyze_image_for_human(card['image_url'])
        card['gemini_guess'] = eval_res.has_human
        card['gemini_confidence'] = eval_res.confidence
        card['gemini_reasoning'] = eval_res.reasoning

    return cards

@st.cache_resource
def get_engine():
    return get_base_engine()

# --- DATA PARSING HELPERS ---
def parse_json_array(raw_val):
    if not raw_val: return []
    
    # Return immediately if SQLAlchemy already parsed the JSONB into a list
    if isinstance(raw_val, list):
        return raw_val
        
    try:
        parsed = json.loads(raw_val)
        return parsed if isinstance(parsed, list) else [parsed]
    except:
        return [str(raw_val).strip('[]"\' ')]
    
# --- IMAGE ROTATION HELPER ---
def fetch_and_rotate_image(image_url: str, rotation_angle: int = 0) -> Image.Image:
    """Downloads an image from URL and applies clockwise rotation dynamically."""
    response = requests.get(image_url)
    img = Image.open(BytesIO(response.content)).convert("RGBA")
    
    if rotation_angle and rotation_angle > 0:
        # PIL rotates counter-clockwise by default, so (360 - angle) rotates clockwise
        img = img.rotate(360 - rotation_angle, expand=True)
        
    return img

# --- DATABASE TRANSACTIONS ---
def fetch_card_batch(engine, search, limit):
    base_query = f"""
        SELECT 
            c.card_id,
            (SPLIT_PART(c.card_id, '-', 2) || '/' || s.total_cards::text) as position_id,
            c.name, 
            c.illustrator, 
            c.rarity, 
            c.market_price, 
            c.image_url, 
            COALESCE(c.rotation_angle, 0) AS rotation_angle,
            c.is_trainer,
            c.human_cameo,
            c.is_shiny,
            c.cameo_frequency, 
            c.cameo_pokemon,
            s.name AS set_name,
            p.grid_group_name AS phys_group,
            p.grid_width,
            p.grid_height,
            p.position_x,
            p.position_y,
            n.story_name,
            n.sequence_order,
            n.narrative_role
        FROM 
            {Tables.CARDS_CARD_DETAILS} c
        LEFT JOIN 
            {Tables.CARDS_SET_DETAILS} s ON c.set_id = s.set_id
        LEFT JOIN 
            {Tables.CARDS_CARD_STORY_GRID_DIMENSIONS} p ON c.card_id = p.card_id
        LEFT JOIN 
            {Tables.CARDS_CARD_CONNECTING_GRID_DIMENSIONS} n ON c.card_id = n.card_id
        WHERE 
            c.supertype != 'Item' AND c.image_url IS NOT NULL
    """
    params = {}
    
    if search:
        base_query += " AND (c.name ILIKE :s OR c.card_id ILIKE :s)"
        params["s"] = f"%{search}%"
  
    base_query += " ORDER BY RANDOM() LIMIT :limit"
    params["limit"] = limit
    
    with engine.connect() as conn:
        results = conn.execute(text(base_query), params).mappings().fetchall()
        return [dict(c) for c in results]

def update_card_record(engine, card_id, data):
    base_query = text(f"""
        UPDATE {Tables.CARDS_CARD_DETAILS} 
        SET illustrator = :illustrator, rarity = :rarity, market_price = :price,
            is_trainer = :trainer, human_cameo = :human_cameo, cameo_frequency = :cameo_freq, cameo_pokemon = :cameo_names,
            is_shiny = :is_shiny, rotation_angle = :rotation_angle,
            updated_at = CURRENT_TIMESTAMP
        WHERE card_id = :id
    """)
    
    phys_query = text(f"""
        INSERT INTO {Tables.CARDS_CARD_STORY_GRID_DIMENSIONS} (card_id, grid_group_name, grid_width, grid_height, position_x, position_y)
        VALUES (:id, :phys_group, :grid_w, :grid_h, :pos_x, :pos_y)
        ON CONFLICT (card_id) DO UPDATE SET
            grid_group_name = EXCLUDED.grid_group_name, grid_width = EXCLUDED.grid_width,
            grid_height = EXCLUDED.grid_height, position_x = EXCLUDED.position_x, position_y = EXCLUDED.position_y;
    """)
    
    narr_query = text(f"""
        INSERT INTO {Tables.CARDS_CARD_CONNECTING_GRID_DIMENSIONS} (card_id, story_name, sequence_order, narrative_role)
        VALUES (:id, :story_name, :seq_order, :narr_role)
        ON CONFLICT (card_id) DO UPDATE SET
            story_name = EXCLUDED.story_name, sequence_order = EXCLUDED.sequence_order,
            narrative_role = EXCLUDED.narrative_role;
    """)

    with engine.begin() as conn:
        conn.execute(base_query, {
            "illustrator": data['illustrator'] or None,
            "rarity": data['rarity'] or None,
            "price": data['price'] if data['price'] > 0 else None,
            "trainer": data['trainer'],
            "human_cameo": data['human_cameo'],
            "cameo_freq": data['cameo_freq'],
            "is_shiny": data['shiny'],
            "cameo_names": json.dumps(data['cameo_names']) if data['cameo_names'] else None,
            "rotation_angle": data.get('rotation_angle', 0),
            "id": card_id
        })
        
        if data['phys_group']:
            conn.execute(phys_query, data | {"id": card_id})
        else:
            conn.execute(text(f"""DELETE FROM {Tables.CARDS_CARD_STORY_GRID_DIMENSIONS} WHERE card_id = :id"""), {"id": card_id})
            
        if data['story_name']:
            conn.execute(narr_query, data | {"id": card_id})
        else:
            conn.execute(text(f"""DELETE FROM {Tables.CARDS_CARD_CONNECTING_GRID_DIMENSIONS} WHERE card_id = :id"""), {"id": card_id})

def fetch_and_stitch_grid(engine, group_name):
    """Fetches all cards in a grid group, applies any saved rotation, and stitches them into a single image."""
    query = text(f"""
        SELECT 
            c.image_url, COALESCE(c.rotation_angle, 0) AS rotation_angle,
            p.grid_width, p.grid_height, p.position_x, p.position_y
        FROM {Tables.CARDS_CARD_STORY_GRID_DIMENSIONS} p
        JOIN {Tables.CARDS_CARD_DETAILS} c ON p.card_id = c.card_id
        WHERE p.grid_group_name = :group_name
        ORDER BY p.position_x ASC
    """)
    
    with engine.connect() as conn:
        pieces = conn.execute(query, {"group_name": group_name}).mappings().fetchall()
        
    if not pieces:
        return None

    grid_w = pieces[0]['grid_width']
    grid_h = pieces[0]['grid_height']
    
    # Download and rotate first piece to calculate canvas dimensions
    base_img = fetch_and_rotate_image(pieces[0]['image_url'], pieces[0]['rotation_angle'])
    card_w, card_h = base_img.size
    
    # --- INFINITE RECURRENCE HANDLER ---
    if grid_w == 0 or grid_h == 0:
        canvas = Image.new('RGBA', (card_w * 3, card_h), (0, 0, 0, 0))
        
        if len(pieces) == 1:
            canvas.paste(base_img, (0, 0), base_img)
            canvas.paste(base_img, (card_w, 0), base_img)
            canvas.paste(base_img, (card_w * 2, 0), base_img)
        else:
            for i in range(3):
                piece = pieces[i % len(pieces)]
                img = fetch_and_rotate_image(piece['image_url'], piece['rotation_angle'])
                canvas.paste(img, (i * card_w, 0), img)
                
        canvas.thumbnail((800, 600), Image.Resampling.LANCZOS)
        return canvas

    # --- STANDARD GRID RENDERING ---
    canvas = Image.new('RGBA', (card_w * grid_w, card_h * grid_h), (0, 0, 0, 0))
    
    for piece in pieces:
        img = fetch_and_rotate_image(piece['image_url'], piece['rotation_angle'])
        paste_x = (piece['position_x'] - 1) * card_w
        paste_y = (piece['position_y'] - 1) * card_h
        
        canvas.paste(img, (paste_x, paste_y), img)
        
    canvas.thumbnail((800, 600), Image.Resampling.LANCZOS)
    return canvas