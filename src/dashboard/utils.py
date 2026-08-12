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
    # Added the JOIN and prefixed columns with 'c.' to avoid ambiguity
    base_query = """
        SELECT 
            c.card_id,
            (SPLIT_PART(c.card_id, '-', 2) || '/ ' || s.total_cards) as position_id,
            c.name, 
            c.illustrator, 
            c.rarity, 
            c.market_price, 
            c.image_url, 
            c.has_trainer, 
            c.cameo_frequency, 
            c.cameo_pokemon,
            s.name AS set_name
        FROM 
            tcg_cards c
        LEFT JOIN 
            card_sets s 
            ON c.set_id = s.set_id
        WHERE 
            REPLACE(c.supertype, 'é', 'e') = 'Pokemon' AND c.image_url IS NOT NULL
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