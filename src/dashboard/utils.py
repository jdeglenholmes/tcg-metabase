# src/dashboard/utils.py
import os
import json
import streamlit as st
from sqlalchemy import text
from src.database.connection import get_engine as get_base_engine

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))

# --- TAXONOMY TRI-TIER ARCHITECTURE ---
CORE_STYLES = [
    "handcrafted_diorama", "textile_craft", "pen_and_ink_stippling",
    "soft_geometric_stencil", "canvas_paintings", "crisp_digital_portrait",
    "pixel_art", "retro_90s_anime"
]

AUTO_STYLES = [
    "3d_cgi_render", "sketchbook_comic", "heavy_pencil",
    "heavy_acrylic_oil", "chalk_pastel", "watercolor_and_ink"
]

SUGGESTED_REMAINING_STYLES = [
    "stained_glass", "pop_art", "wood_block", "ukiyo_e", "standard_generic"
]

ART_STYLE_KEYS = CORE_STYLES + AUTO_STYLES + SUGGESTED_REMAINING_STYLES

AESTHETIC_KEYS = [
    "kinetic", "chaotic", "modern", "whimsical", "legendary", "neutral",
    "minimalist", "maximalist", "cinematic", "surrealist", "traditional_hand_painted",
    "eerie_gothic", "cottagecore", "lush_botanical", "neon_cyberpunk", "high_stakes_showdown"
]
@st.cache_resource
def get_engine():
    return get_base_engine()

# --- DATA PARSING HELPERS ---
def parse_json_array(raw_val):
    if not raw_val: return []
    try:
        parsed = json.loads(raw_val)
        return parsed if isinstance(parsed, list) else [parsed]
    except:
        return [str(raw_val).strip('[]"\' ')]
    
def parse_json_column(raw_val, fallback):
    if not raw_val: return fallback
    try:
        parsed = json.loads(raw_val)
        return parsed[0] if isinstance(parsed, list) and len(parsed) > 0 else parsed
    except: 
        return str(raw_val).strip('[]"\' ')

# --- DATABASE TRANSACTIONS ---
def fetch_card_batch(engine, search, limit):
    base_query = """
        SELECT card_id, name, illustrator, rarity, market_price, image_url, 
               art_style, card_aesthetic, has_trainer, cameo_frequency, cameo_pokemon
        FROM tcg_cards 
        WHERE REPLACE(supertype, 'é', 'e') = 'Pokemon' AND image_url IS NOT NULL
    """
    params = {}
    
    if search:
        base_query += " AND (name ILIKE :s OR card_id ILIKE :s)"
        params["s"] = f"%{search}%"
  
    base_query += " ORDER BY RANDOM() LIMIT :limit"
    params["limit"] = limit
    
    with engine.connect() as conn:
        results = conn.execute(text(base_query), params).mappings().fetchall()
        return [dict(c) for c in results]

def update_card_record(engine, card_id, data):
    query = text("""
        UPDATE tcg_cards 
        SET art_style = :style, 
            card_aesthetic = :aesthetic,
            illustrator = :illustrator,
            rarity = :rarity,
            market_price = :price,
            has_trainer = :trainer,
            cameo_frequency = :cameo_freq,
            cameo_pokemon = :cameo_names,
            labeled_by = 'Human_Audit', 
            updated_at = CURRENT_TIMESTAMP
        WHERE card_id = :id
    """)
    
    params = {
        "style": json.dumps([data['style']]),
        "aesthetic": json.dumps(data['aesthetic']) if data['aesthetic'] else None,
        "illustrator": data['illustrator'] if data['illustrator'] else None,
        "rarity": data['rarity'] if data['rarity'] else None,
        "price": data['price'] if data['price'] > 0 else None,
        "trainer": data['trainer'],
        "cameo_freq": data['cameo_freq'],
        "cameo_names": json.dumps(data['cameo_names']) if data['cameo_names'] else None,
        "id": card_id
    }
    
    with engine.begin() as conn:
        conn.execute(query, params)