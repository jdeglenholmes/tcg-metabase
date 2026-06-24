# src/dashboard/utils.py
import streamlit as st
import pandas as pd
import yaml
import subprocess
import sys
import datetime 
import json
import re  
from sqlalchemy import text
import requests
import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
from src.database.connection import get_engine

# --- TAXONOMIES ---
ART_STYLE_KEYS = [
    # --- Physical & Traditional Media ---
    "watercolor_and_ink", "heavy_acrylic_oil", "chalk_pastel", "textile_craft", 
    "handcrafted_diorama", "pen_and_ink_stippling",
    
    # --- Digital & Commercial ---
    "crisp_digital_portrait", "3d_cgi_render", "pixel_art", "retro_90s_anime", 
    "standard_generic", "comic_book_illustration", "stained_glass", "pop_art",
    
    # --- Cultural & Historical ---
    "ukiyo_e"
]

AESTHETIC_KEYS = [
    "kinetic", "chaotic", "modern", "whimsical", "legendary", "neutral",
    "minimalist", "maximalist", "cinematic", "surrealist", "traditional_hand_painted",
    "eerie_gothic", "cottagecore", "lush_botanical", "neon_cyberpunk", "high_stakes_showdown",
    "celestial", "has_cameo", "is_trainer_gallery"
]

# --- UI COMPONENTS ---
def render_sidebar():
    with st.sidebar:
        st.title("TCG Auditor")
        st.page_link("app.py", label="Home", icon="🏠")
        st.page_link("pages/1_🕵️_Human_Labelling.py", label="Human Labelling", icon="🕵️")
        st.page_link("pages/2_🤖_Ask_AI_Labelling.py", label="Ask AI Labelling", icon="🤖")
        st.page_link("pages/3_📊_Label_Metrics_Dashboard.py", label="Label Metrics Dashboard", icon="📊")
        st.divider()
        st.caption("v2.0 Cloud Architecture")

# --- DATABASE OPERATIONS ---
def get_unlabeled_cards(limit=1):
    """Fetches cards that the active learning loop flagged as needing manual review."""
    engine = get_engine()
    
    query = """
        SELECT card_id, name, supertype, image_url, set_id 
        FROM tcg_cards 
        WHERE art_style = '"Manual review needed"'
        AND image_url IS NOT NULL
        LIMIT :limit;
    """
    with engine.connect() as conn:
        df = pd.read_sql_query(text(query), conn, params={"limit": limit})
    return df

def save_label_to_db(card_id, selections):
    """
    Saves manual tag selections to the database. 
    User tracking is disabled; logs as 'Human_Audit'.
    """
    engine = get_engine()
    tags_json = json.dumps(selections)
    
    # Extract the true values for the dedicated columns
    true_art = [k for k, v in selections.items() if v and k in ART_STYLE_KEYS]
    true_aes = [k for k, v in selections.items() if v and k in AESTHETIC_KEYS]
    
    with engine.begin() as conn:
        query = """
            UPDATE tcg_cards 
            SET tags = :tags, 
                labeled_by = 'Human_Audit', -- Hardcoded to replace the old user_name
                art_style = :art, 
                card_aesthetic = :aes, 
                updated_at = CURRENT_TIMESTAMP
            WHERE card_id = :card_id;
        """
        conn.execute(
            text(query), 
            {
                "tags": tags_json, 
                "art": json.dumps(true_art), 
                "aes": json.dumps(true_aes), 
                "card_id": card_id
            }
        )