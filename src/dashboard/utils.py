# src/dashboard/utils.py
import os
import json
import streamlit as st
from sqlalchemy import text
from src.database.connection import get_engine as get_base_engine

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))

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
        SELECT card_id, name, illustrator, rarity, market_price, 
        image_url, has_trainer, cameo_frequency, cameo_pokemon
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
        SET
            illustrator = :illustrator,
            rarity = :rarity,
            market_price = :price,
            has_trainer = :trainer,
            cameo_frequency = :cameo_freq,
            cameo_pokemon = :cameo_names,
            updated_at = CURRENT_TIMESTAMP
        WHERE card_id = :id
    """)
    
    params = {
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