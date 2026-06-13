# src/dashboard/utils.py
import streamlit as st
import pandas as pd
import os
import yaml
import subprocess
import sys
import datetime 
import json
import re  
from sqlalchemy import text
from src.database.connection import get_engine
import torch
import clip
import requests

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))

# --- TAXONOMIES ---
ART_STYLE_KEYS = [
    # --- Physical & Traditional Media ---
    "watercolor_and_ink", "heavy_acrylic_oil", "chalk_pastel", "textile_craft", 
    "handcrafted_diorama", "pen_and_ink_stippling",
    
    # --- Digital & Commercial ---
    "crisp_digital_portrait", "3d_cgi_render", "pixel_art", "retro_90s_anime", 
    
    # --- Highly Stylized / Genre ---
    "ukiyo_e", "comic_book_illustration", "stained_glass", "pop_art",
    "standard_generic"
]

AESTHETIC_KEYS = [
    "kinetic", "chaotic", "cinematic", "modern", "whimsical", "legendary", 
    "neutral", "cottagecore", "lush_botanical", "high_stakes_showdown", 
    "celestial", "neon_cyberpunk", "eerie_gothic", "comical_derpy",
    "minimalist", "maximalist", "surrealist"
]

BINARY_FEATURES = ["has_cameo", "is_trainer_gallery"]
ALL_KEYS = ART_STYLE_KEYS + AESTHETIC_KEYS + BINARY_FEATURES

TARGET_NAMES = [
    '3d_cgi_render', 'celestial', 'chalk_pastel', 'chaotic', 'cinematic', 
    'comic_book_illustration', 'comical_derpy', 'cottagecore', 'crisp_digital_portrait', 
    'eerie_gothic', 'handcrafted_diorama', 'has_cameo', 'heavy_acrylic_oil', 
    'high_stakes_showdown', 'is_trainer_gallery', 'kinetic', 'legendary', 
    'lush_botanical', 'maximalist', 'minimalist', 'modern', 'neon_cyberpunk', 
    'neutral', 'pixel_art', 'pop_art', 'retro_90s_anime', 'stained_glass', 
    'standard_generic', 'surrealist', 'textile_craft', 'ukiyo_e', 
    'watercolor_and_ink', 'whimsical'
]

# --- QUALITY ASSURANCE RULES ---
ARTIST_ANCHORS = {
    "Asako Ito": "textile_craft",           # Exclusively knits yarn/amigurumi
    "Yuka Morii": "handcrafted_diorama",    # Exclusively sculpts clay models
    "5ban Graphics": "3d_cgi_render",       # Studio that exclusively makes 3D renders
    "PLANETA": "3d_cgi_render",             # 3D CGI studio
    "N-DESIGN Inc.": "3d_cgi_render",       # 3D CGI studio
    "Tomokazu Komiya": "heavy_acrylic_oil", # Iconic thick, messy oil/acrylic painter
    "sowsow": "chalk_pastel",               # Distinctive soft pastel/chalk style
    "Shinji Kanda": "surrealist",           # Distinctive scratchy, psychedelic surrealism
    "Yu Nagaba": "minimalist",              # Exclusively does stark, black-and-white line art
    "AKIRA EGAWA": "maximalist",            # Famous for hyper-dense, edge-to-edge detailing
    "OOYAMA": "comical_derpy",              # Known for flat, funny, derpy faces
    "Kanahei": "comical_derpy",             # Known for round, goofy, storybook designs
    "Naoki Saito": "crisp_digital_portrait" # The quintessential modern anime digital portrait artist
}

@st.cache_data(ttl=86400)
def fetch_all_pokemon_sets():
    try:
        response = requests.get("https://api.pokemontcg.io/v2/sets")
        if response.status_code == 200:
            sets = response.json().get('data', [])
            return sorted(sets, key=lambda x: x.get('releaseDate', ''), reverse=True)
        return []
    except Exception as e:
        st.error(f"Failed to fetch sets: {e}")
        return []
    
@st.cache_resource
def load_clip_model():
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model, preprocess = clip.load("ViT-B/32", device=device)
    return model, device

def run_pipeline_live(cmd_list, step_name):
    log_dir = os.path.join(PROJECT_ROOT, "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "app_log.txt")
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    st.write(f"⚙️ Executing: **{step_name}**")
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    try:
        process = subprocess.Popen(
            cmd_list, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
            text=True, cwd=PROJECT_ROOT, bufsize=1, encoding='utf-8'
        )
        
        output_lines = []
        current_line = ""
        
        while True:
            char = process.stdout.read(1)
            if not char and process.poll() is not None: break
            
            if char in ['\r', '\n']:
                clean_line = current_line.strip()
                if clean_line:
                    match = re.search(r'(\d{1,3})%\|', clean_line)
                    if match:
                        pct = min(int(match.group(1)), 100)
                        progress_bar.progress(pct / 100.0)
                    status_text.code(clean_line)
                    output_lines.append(clean_line)
                current_line = ""
            else:
                current_line += char
                
        process.wait()
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"\n[{timestamp}] ✅ DONE: {step_name}\n")
        status_text.success("Process Complete!")
        return process.returncode == 0, "\n".join(output_lines)
    except Exception as e:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"\n[{timestamp}] ❌ ERROR: {step_name} FAILED\n{str(e)}\n")
        return False, str(e)

def get_set_name_mapping():
    mapping = {}
    raw_yaml_sets = {}
    try:
        with open(os.path.join(PROJECT_ROOT, "config/sets.yaml"), "r") as f:
            config = yaml.safe_load(f)
            raw_yaml_sets = config.get("sets", {})
            
        for readable_slug, set_id in raw_yaml_sets.items():
            if readable_slug.startswith('sv0') or readable_slug == set_id: continue
            clean_name = readable_slug.replace('-', ' ').title()
            if clean_name.endswith(" Gg"): clean_name = clean_name.replace(" Gg", " (Galarian Gallery)")
            if clean_name.endswith(" Tg"): clean_name = clean_name.replace(" Tg", " (Trainer Gallery)")
            mapping[set_id] = clean_name
    except Exception: pass
    return mapping, raw_yaml_sets

SET_NAME_MAPPING, RAW_YAML_SETS = get_set_name_mapping()
CHRONOLOGICAL_ORDER = list(RAW_YAML_SETS.values())

def format_set_name(prefix): 
    return SET_NAME_MAPPING.get(prefix, prefix.upper())

def get_labeling_state(selected_set, current_user):
    engine = get_engine()
    with engine.connect() as conn:
        query = """
        SELECT card_id, name, illustrator, image_url, labeled_by, tags, image_embedding 
        FROM tcg_cards 
        WHERE card_id LIKE :prefix AND image_url IS NOT NULL;
        """
        db_df = pd.read_sql_query(text(query), conn, params={"prefix": f"{selected_set}-%"})
        
    user_history = pd.DataFrame()
    if not db_df.empty:
        user_history = db_df[(db_df['labeled_by'] == current_user) & (db_df['tags'].notnull())]
    
    def extract_number(cid):
        parts = cid.split('-')
        if len(parts) > 1:
            match = re.search(r'\d+', parts[-1])
            if match: return int(match.group())
        return 99999
        
    if not db_df.empty:
        db_df['sort_key'] = db_df['card_id'].apply(extract_number)
        db_df = db_df.sort_values('sort_key').drop(columns=['sort_key']).reset_index(drop=True)
            
    return db_df, user_history

def save_label_to_db(card_id, user_name, selections):
    engine = get_engine()
    tags_json = json.dumps(selections)
    true_art = [k for k, v in selections.items() if v and k in ART_STYLE_KEYS]
    true_aes = [k for k, v in selections.items() if v and k in AESTHETIC_KEYS]
    
    with engine.begin() as conn:
        query = """
            UPDATE tcg_cards 
            SET tags = :tags, labeled_by = :user_name, art_style = :art, card_aesthetic = :aes, updated_at = CURRENT_TIMESTAMP
            WHERE card_id = :card_id;
        """
        conn.execute(text(query), {"tags": tags_json, "user_name": user_name, "art": json.dumps(true_art), "aes": json.dumps(true_aes), "card_id": card_id})

def render_sidebar():
    """Renders the shared sidebar and manages session state across all pages."""
    st.sidebar.title("🎴 TCG ML Studio")
    
    if "user_name" not in st.session_state:
        st.session_state.user_name = ""
        
    user_name = st.sidebar.text_input("User Name", value=st.session_state.user_name, placeholder="👤 i.e. Jacob", label_visibility="collapsed")
    st.session_state.user_name = user_name
    
    if not st.session_state.user_name:
        st.sidebar.info("👈 Please enter your name to access the studio.")
        st.stop()
        
    st.sidebar.write("---")
    
    engine = get_engine()
    with engine.connect() as conn:
        set_query = "SELECT DISTINCT split_part(card_id, '-', 1) as set_prefix FROM tcg_cards;"
        raw_db_sets = [r[0] for r in conn.execute(text(set_query)).fetchall() if r[0]]
        
    all_sets = sorted(raw_db_sets, key=lambda x: CHRONOLOGICAL_ORDER.index(x) if x in CHRONOLOGICAL_ORDER else 9999)
    
    if "selected_set" not in st.session_state:
        st.session_state.selected_set = all_sets[0] if all_sets else None
        
    st.sidebar.caption("📂 Select Working Set")
    
    current_index = 0
    if st.session_state.selected_set in all_sets:
        current_index = all_sets.index(st.session_state.selected_set)
        
    selected_set = st.sidebar.selectbox(
        "set_select", 
        all_sets, 
        index=current_index,
        format_func=format_set_name, 
        label_visibility="collapsed"
    )
    st.session_state.selected_set = selected_set
    
    return st.session_state.user_name, st.session_state.selected_set