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
import joblib
import ast
import os
import numpy as np

import requests

@st.cache_data(ttl=86400) # Caches the data for 24 hours to prevent API spam
def fetch_all_pokemon_sets():
    """Fetches all sets dynamically from the Pokémon TCG API."""
    try:
        response = requests.get("https://api.pokemontcg.io/v2/sets")
        if response.status_code == 200:
            sets = response.json().get('data', [])
            # Sort them by release date, newest first!
            return sorted(sets, key=lambda x: x.get('releaseDate', ''), reverse=True)
        else:
            return []
    except Exception as e:
        st.error(f"Failed to fetch sets: {e}")
        return []

st.set_page_config(page_title="TCG ML Studio", layout="wide", page_icon="🎴")

# Adjusted for app.py being in src/dashboard/
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))

# --- TAXONOMIES ---
ART_STYLE_KEYS = [
    "minimalist", "maximalist", "traditional_hand_painted", 
    "crisp_digital_portrait", "cinematic", "handcrafted_diorama", 
    "surrealist", "standard_generic", "pop_art", "comic_book_illustration"
]

AESTHETIC_KEYS = [
    "kinetic", "chaotic", "modern", "whimsical", "legendary", "neutral"
]

BINARY_FEATURES = ["has_cameo", "is_trainer_gallery"]
ALL_KEYS = ART_STYLE_KEYS + AESTHETIC_KEYS + BINARY_FEATURES

# --- QUALITY ASSURANCE RULES ---
ARTIST_ANCHORS = {
    "Asako Ito": "handcrafted_diorama",
    "Yuka Morii": "handcrafted_diorama",
    "5ban Graphics": "crisp_digital_portrait",
    "PLANETA": "crisp_digital_portrait",
    "N-DESIGN Inc.": "crisp_digital_portrait",
    "Tomokazu Komiya": "surrealist",
    "Shinji Kanda": "surrealist",
    "AKIRA EGAWA": "maximalist",
    "Ooyama": "whimsical"
}

# --- HELPER FUNCTIONS ---
def run_pipeline_live(cmd_list, step_name):
    """Runs a command, captures tqdm output, and updates a Streamlit progress bar live."""
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

def format_set_name(prefix): return SET_NAME_MAPPING.get(prefix, prefix.upper())

def get_labeling_state(selected_set, current_user):
    engine = get_engine()
    with engine.connect() as conn:
        # 🚨 Notice we now select 'illustrator' for our QA Audit
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

def run_local_audit(user_history_df):
    """Scans the user's labeled cards in the current set for artist inconsistencies."""
    flags = {}
    if user_history_df.empty: return flags
    
    for _, row in user_history_df.iterrows():
        artist = str(row.get('illustrator', ''))
        tags = row.get('tags', {})
        if isinstance(tags, str):
            try: tags = json.loads(tags)
            except: tags = {}
            
        for anchor_name, required_tag in ARTIST_ANCHORS.items():
            if anchor_name in artist:
                if not tags.get(required_tag):
                    flags[row['card_id']] = f"Artist **{anchor_name}** requires tag: `{required_tag}`"
                break
    return flags


# --- HYPER-CLEAN SIDEBAR ---
st.sidebar.title("🎴 TCG ML Studio")
user_name = st.sidebar.text_input("User Name", placeholder="👤 User Name...", label_visibility="collapsed")

if not user_name:
    st.info("👈 Please enter your user name in the sidebar to access the studio.")
    st.stop()

st.sidebar.write("---")
app_mode = st.sidebar.radio("Navigation", ["📥 Data Ingestor", "🏷️ Data Labeler", "🧪 Model Testing"])
st.sidebar.write("---")

engine = get_engine()

# Smart Set Selector
selected_set = None
if app_mode in ["📥 Data Ingestor", "🏷️ Data Labeler"]:
    with engine.connect() as conn:
        set_query = "SELECT DISTINCT split_part(card_id, '-', 1) as set_prefix FROM tcg_cards;"
        raw_db_sets = [r[0] for r in conn.execute(text(set_query)).fetchall() if r[0]]
        
    all_sets = sorted(raw_db_sets, key=lambda x: CHRONOLOGICAL_ORDER.index(x) if x in CHRONOLOGICAL_ORDER else 9999)
    st.sidebar.caption("📂 Select Working Set")
    selected_set = st.sidebar.selectbox("set_select", all_sets, format_func=format_set_name, label_visibility="collapsed")


# ==========================================
# MODULE 1: DATA INGESTOR
# ==========================================
if app_mode == "📥 Data Ingestor":
    st.title("📥 Data Ingestor")
    st.write("Manage raw API data and generate visual embeddings for the Active Learning pipeline.")
    
    # --- 1. DATASET HEALTH DASHBOARD ---
    st.subheader("📊 Dataset Health")
    with engine.connect() as conn:
        # Safely fetch database metrics
        total_cards = conn.execute(text("SELECT COUNT(*) FROM tcg_cards")).scalar() or 0
        total_sets = conn.execute(text("SELECT COUNT(DISTINCT split_part(card_id, '-', 1)) FROM tcg_cards")).scalar() or 0
        total_embeddings = conn.execute(text("SELECT COUNT(*) FROM tcg_cards WHERE image_embedding IS NOT NULL")).scalar() or 0
        total_labeled = conn.execute(text("SELECT COUNT(*) FROM tcg_cards WHERE tags IS NOT NULL")).scalar() or 0
        
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Cards Ingested", f"{total_cards:,}")
    m2.metric("Sets Tracked", f"{total_sets:,}")
    
    # Calculate embedding coverage percentage safely
    pct_embedded = (total_embeddings / max(total_cards, 1)) * 100
    m3.metric("Embeddings Generated", f"{total_embeddings:,}", f"{pct_embedded:.1f}% Coverage", delta_color="normal")
    
    m4.metric("Human Verified Labels", f"{total_labeled:,}")
    st.write("---")
    
    # Fetch all sets dynamically for the dropdown
    all_sets = fetch_all_pokemon_sets()
    
    # 1. Run a single highly efficient SQL query to get the exact status of every set in your DB
    db_status_query = text("""
        SELECT 
            split_part(card_id, '-', 1) as set_prefix, 
            COUNT(*) as total_cards, 
            SUM(CASE WHEN image_embedding IS NOT NULL THEN 1 ELSE 0 END) as embedded_cards
        FROM tcg_cards 
        GROUP BY set_prefix;
    """)
    
    with engine.connect() as conn:
        db_results = conn.execute(db_status_query).fetchall()
        
    # Convert SQL results into a quick lookup dictionary
    db_state = {row.set_prefix: {'total': row.total_cards, 'embedded': row.embedded_cards} for row in db_results}
    
    # 2. Build the dropdown options with the Traffic Light logic
    set_options = {}
    if all_sets:
        for s in all_sets:
            set_id = s['id']
            set_name = s['name']
            
            # Check this specific API set against our Database state
            state = db_state.get(set_id)
            
            if not state or state['total'] == 0:
                status_icon = "🔴"  # Not ingested at all
            elif state['embedded'] < state['total']:
                status_icon = "🟡"  # Ingested, but missing embeddings
            else:
                status_icon = "🟢"  # Fully ingested and embedded (Ready!)
                
            set_options[set_id] = f"{status_icon} {set_name} ({set_id})"

    # --- TWO COLUMN LAYOUT ---
    col_left, col_right = st.columns(2)
    
    with col_left:
        st.subheader("🎯 Targeted Ingestion")
        st.info("Legend: 🔴 Not Ingested | 🟡 Missing Embeddings | 🟢 Ready for Labeler")
        
        selected_set_id = st.selectbox(
            "Search and select a set:", 
            options=list(set_options.keys()), 
            format_func=lambda x: set_options.get(x, x)
        )
        
        if st.button("📥 Ingest & Process Target Set", type="primary", use_container_width=True):
            # Phase 1: Ingest
            success_ingest, _ = run_pipeline_live(
                [sys.executable, "-m", "src.ingest.run", "--ingest", "--set_name", selected_set_id], 
                f"Ingesting API Data: {set_options[selected_set_id]}"
            )
            
            # Phase 2: Instantly Enrich (ONLY if Phase 1 succeeded)
            if success_ingest:
                success_enrich, _ = run_pipeline_live(
                    [sys.executable, "-m", "src.ingest.run", "--enrich", "--set_name", selected_set_id], 
                    f"Generating Visual Embeddings: {set_options[selected_set_id]}"
                )
                if success_enrich:
                    st.success(f"✨ {selected_set_id} fully processed and ready for the Data Labeler!")
                else:
                    st.error("⚠️ Ingestion succeeded, but visual embedding generation failed.")
            else:
                # FIX 3: Catch the ingestion failure and stop the pipeline!
                st.error(f"❌ Ingestion completely failed for '{selected_set_id}'. The pipeline has been halted.")
                
    with col_right:
        st.subheader("🌍 Bulk Operations")
        st.warning("These operations scan the entire database. They may take a significant amount of time depending on hardware limits.")
        
        # Safe Bulk Action 1: Fill missing gaps
        if st.button("🧠 Process All Missing Embeddings", use_container_width=True):
            st.caption("Scans all ingested cards and generates embeddings for any that are missing.")
            success, _ = run_pipeline_live(
                [sys.executable, "-m", "src.ingest.run", "--enrich"], 
                "Bulk Generating Missing Embeddings"
            )
            if success: st.rerun()

        # Heavy Bulk Action 2: The "Do Everything" button
        st.markdown("**Mass API Sync**")
        if st.button("⚠️ Ingest & Process ALL API Sets", use_container_width=True):
            st.error("This will attempt to ingest 15,000+ cards from the Pokémon API and run them through the Neural Network. Are you sure?")
            if st.button("🚨 Yes, Execute Mass Sync"):
                for s_id in set_options.keys():
                    # Sequential loop for the entire API history
                    st.toast(f"Starting {s_id}...")
                    run_pipeline_live([sys.executable, "-m", "src.ingest.run", "--ingest", "--set_name", s_id], f"Ingesting {s_id}")
                    run_pipeline_live([sys.executable, "-m", "src.ingest.run", "--enrich", "--set_name", s_id], f"Embedding {s_id}")
                st.balloons()

# ==========================================
# MODULE 2: DATA LABELER (With Embedded QA & AI Assist)
# ==========================================
elif app_mode == "🏷️ Data Labeler":
    st.title(f"🏷️ Labeler: {format_set_name(selected_set)}")
    
    db_df, user_history = get_labeling_state(selected_set, user_name)
    
    if db_df.empty:
        st.warning("No cards found for this set. Please run Ingestion in the Data Ingestor!")
        st.stop()
        
    user_history_ids = user_history['card_id'].values if not user_history.empty else []
    
    # --- RUN QA AUDIT ---
    qa_flags = run_local_audit(user_history)
    
    display_map = {}
    for _, row in db_df.iterrows():
        cid = row['card_id']
        prefix = "🚨 " if cid in qa_flags else ("✅ " if cid in user_history_ids else "")
        display_map[cid] = f"{prefix}{row['name']} / {cid.split('-')[-1]}"
    
    # --- TOP NAVIGATION BAR ---
    nav_col1, nav_col2, nav_col3 = st.columns([2, 1, 1])
    with nav_col1:
        card_list = db_df['card_id'].tolist()
        if "nav_selectbox" in st.session_state and st.session_state["nav_selectbox"] not in card_list: del st.session_state["nav_selectbox"]
        if "advance_to" in st.session_state:
            if st.session_state["advance_to"] in card_list: st.session_state["nav_selectbox"] = st.session_state["advance_to"]
            del st.session_state["advance_to"]
        elif "nav_selectbox" not in st.session_state:
            unlabeled_df = db_df[~db_df['card_id'].isin(user_history_ids)]
            st.session_state["nav_selectbox"] = unlabeled_df.iloc[0]['card_id'] if not unlabeled_df.empty else card_list[0]
                
        selected_id = st.selectbox("card_nav", options=card_list, format_func=lambda x: display_map[x], key="nav_selectbox", label_visibility="collapsed")
        current_card = db_df[db_df['card_id'] == selected_id].iloc[0]

    with nav_col2: st.metric("Set Progress", f"{len([i for i in user_history_ids if str(i).startswith(selected_set)])} / {len(db_df)}")
    with nav_col3: st.metric("Total User Labels", len(user_history))
        
    st.write("---")
    
    # --- QA WARNING BANNER ---
    if qa_flags:
        st.error(f"🚨 **Quality Assurance Alert:** {len(qa_flags)} labeled cards in this set conflict with known Artist rules. Check the dropdown menu for the 🚨 icon.")
    
    # --- MAIN LABELING AREA ---
    col1, col2 = st.columns([1, 2]) 
    with col1:
        st.image(current_card['image_url'], use_container_width=True)
        st.caption(f"**Illustrator:** {current_card['illustrator']}")
        
    with col2:
        # Show specific QA error for the active card
        if selected_id in qa_flags:
            st.warning(f"**QA Flag on this card:** {qa_flags[selected_id]}")
            
        # --- LOAD THE CUSTOM AI MODEL ---
        ai_model = None
        model_path = os.path.join("src", "ml", "models", "custom_classifier.pkl")
        if os.path.exists(model_path):
            ai_model = joblib.load(model_path)

        existing_data = {}
        is_ai_guess = False
        
        # --- STATE 1: HUMAN EDITS ---
        if selected_id in user_history_ids:
            tags_data = user_history[user_history['card_id'] == selected_id].iloc[0].get('tags', {})
            if isinstance(tags_data, str):
                try: tags_data = json.loads(tags_data)
                except: tags_data = {}
            for k in ALL_KEYS: existing_data[k] = bool(tags_data.get(k, 0))
            st.info("👤 You have previously labeled this card. Editing mode.")
            
        # --- STATE 2: AI PRE-FILL (ACTIVE LEARNING) ---
        elif ai_model is not None and current_card.get('image_embedding'):
            try:
                # Convert the string embedding from the DB back to a numpy array
                embedding_str = current_card['image_embedding']
                embedding_list = ast.literal_eval(embedding_str)
                X_input = np.array(embedding_list).reshape(1, -1)
                
                # Ask the model for probabilities and apply the custom 25% threshold
                y_probs = ai_model.predict_proba(X_input)
                for idx, key in enumerate(ALL_KEYS):
                    prob_true = y_probs[idx][0, 1]
                    existing_data[key] = bool(prob_true >= 0.25)
                    
                is_ai_guess = True
                st.success("🤖 AI has pre-filled its best guesses! Please verify and correct.")
            except Exception as e:
                st.warning(f"AI Prediction failed: {e}")
                
        # --- STATE 3: BLANK MANUAL FALLBACK ---
        else:
            if ai_model is None:
                st.caption("No AI model found. Manual labeling mode. (Go train the model!)")
            else:
                st.caption("Embedding missing for this card. Manual labeling mode.")

        with st.form(key=f"label_form_{selected_id}", clear_on_submit=False):
            tab_art, tab_aes, tab_feat = st.tabs(["🎨 Art Styles", "✨ Card Aesthetics", "🔍 Card Features"])
            selections = {}
            
            def render_checkboxes(keys, tab_container):
                col_a, col_b = tab_container.columns(2)
                for idx, key in enumerate(keys):
                    display_name = key.replace('_', ' ').title()
                    target_col = col_a if idx % 2 == 0 else col_b
                    
                    # Highlight the specific boxes the AI triggered
                    label = f"✨ {display_name}" if (is_ai_guess and existing_data.get(key, False)) else display_name
                    selections[key] = target_col.checkbox(label, value=existing_data.get(key, False))

            render_checkboxes(ART_STYLE_KEYS, tab_art)
            render_checkboxes(AESTHETIC_KEYS, tab_aes)
            render_checkboxes(BINARY_FEATURES, tab_feat)
            
            st.write("---")
            
            # Dynamic button text based on whether the human is creating from scratch or verifying the AI
            button_text = "💾 Save Human Verification & Auto-Advance" if is_ai_guess else "💾 Save & Auto-Advance"
            
            if st.form_submit_button(button_text, use_container_width=True, type="primary"):
                save_label_to_db(selected_id, user_name, selections)
                current_idx = card_list.index(selected_id)
                if current_idx + 1 < len(card_list): st.session_state["advance_to"] = card_list[current_idx + 1]
                st.rerun()

# ==========================================
# MODULE 3: MODEL TESTING & TUNING
# ==========================================
elif app_mode == "🧪 Model Testing":
    st.title("🧪 Model Testing & Tuning")
    st.write("Evaluate your machine learning models directly against your human-labeled Ground Truth database.")
    st.write("---")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("🤖 Zero-Shot CLIP Baseline")
        st.markdown("Evaluates how well the out-of-the-box CLIP model performs using your text prompts.")
        if st.button("📊 Generate CLIP Report Card", use_container_width=True):
            with st.spinner("Analyzing CLIP predictions against Ground Truth..."):
                try:
                    result = subprocess.run([sys.executable, "-m", "src.ingest.evaluate"], capture_output=True, text=True, cwd=PROJECT_ROOT)
                    st.success("Evaluation Complete!")
                    st.text(result.stdout)
                except Exception as e: st.error(f"Error running evaluation: {e}")

    with col2:
        st.subheader("🚀 Train & Test Custom Model")
        st.markdown("""
        Train a **Multi-Layer Perceptron (MLP) Neural Network** layer directly on top of your 512-dimensional CLIP image embeddings.
        
        Unlike a simple linear baseline, this non-linear neural network maps complex, curved relationships in the visual data—allowing it to better learn the subtle boundary lines between intricate art styles and aesthetics.
        """)
        if st.button("🚀 Train Custom Model"):
            with st.spinner("🧠 Initializing Multi-Layer Perceptron architecture..."):
                try:
                    result = subprocess.run([sys.executable, "-m", "src.ml.train_model"], capture_output=True, text=True, cwd=PROJECT_ROOT)
                    st.success("Training Complete!")
                    st.text(result.stdout)
                except Exception as e: st.error(f"Error training model: {e}")
                pass
            st.success("🎯 Custom Neural Network trained and deployed successfully!")
            