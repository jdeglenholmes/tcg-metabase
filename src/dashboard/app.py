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

st.set_page_config(page_title="TCG ML Studio", layout="wide", page_icon="🎴")

# Adjusted for app.py being in src/dashboard/
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))

# --- TAXONOMIES ---
ART_STYLE_KEYS = [
    "minimalist", "maximalist", "traditional_watercolor", 
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
        query = "SELECT card_id, name, illustrator, image_url, labeled_by, tags FROM tcg_cards WHERE card_id LIKE :prefix AND image_url IS NOT NULL;"
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
user_name = st.sidebar.text_input("annotator_name", placeholder="👤 Annotator Name...", label_visibility="collapsed")

if not user_name:
    st.info("👈 Please enter your annotator name in the sidebar to access the studio.")
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
    st.write("Manage raw API data and run machine learning enrichment pipelines.")
    
    st.subheader("🚀 Bulk Operations (Auto-ML)")
    st.write("Instantly run the machine learning pipeline on every set that contains human tags.")
    
    if st.button("⚡ Auto-Enrich All Tagged Sets", use_container_width=True, type="primary"):
        with engine.connect() as conn:
            tagged_sets_query = text("SELECT DISTINCT LOWER(split_part(card_id, '-', 1)) FROM tcg_cards WHERE tags IS NOT NULL;")
            sets_to_process = [r[0] for r in conn.execute(tagged_sets_query).fetchall() if r[0]]
            
        if not sets_to_process:
            st.info("No tagged cards found in the database yet!")
        else:
            st.success(f"🎯 Found {len(sets_to_process)} sets with human tags. Commencing Bulk Enrichment...")
            success_count = 0
            for s_prefix in sets_to_process:
                enrich_cmd = [sys.executable, "-m", "src.ingest.run", "--enrich", "--set_name", s_prefix]
                is_ok, _ = run_pipeline_live(enrich_cmd, f"Auto-Enriching: {format_set_name(s_prefix)}")
                if is_ok: success_count += 1
                    
            if success_count == len(sets_to_process):
                st.balloons()
                st.success("✅ All tagged sets are fully enriched! Ready for Model Testing.")
            else:
                st.warning(f"⚠️ Processed {success_count}/{len(sets_to_process)} sets. Check the logs.")
    
    st.write("---")
    st.subheader(f"🛠️ Single Set Maintenance: {format_set_name(selected_set)}")
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("📥 1. Ingest Raw API Data", use_container_width=True):
            reverse_yaml = {v: k for k, v in RAW_YAML_SETS.items()}
            slug_to_ingest = reverse_yaml.get(selected_set, selected_set)
            success, _ = run_pipeline_live([sys.executable, "-m", "src.ingest.run", "--ingest", "--set_name", slug_to_ingest], f"Ingesting: {selected_set}")
            if success: st.rerun()
                
    with col2:
        if st.button("🧠 2. Run ML Enrichment", use_container_width=True):
            success, _ = run_pipeline_live([sys.executable, "-m", "src.ingest.run", "--enrich", "--set_name", selected_set], f"Enriching: {selected_set}")
            if success: st.rerun()

    with st.expander("⚠️ Advanced Set Maintenance", expanded=False):
        st.warning(f"**Danger Zone:** These actions will modify existing records for **{format_set_name(selected_set)}**.")
        if st.button("🔄 Reset Enrichment Status", type="secondary"):
            with engine.begin() as conn:
                conn.execute(text("""
                    UPDATE tcg_cards SET enrichment_status = 'pending', art_style = NULL, card_aesthetic = NULL, image_embedding = NULL
                    WHERE LOWER(set_id) = :set_id;
                """), {"set_id": selected_set.lower()})
            st.success(f"✅ Reset complete! {format_set_name(selected_set)} is ready to be re-enriched.")

        st.markdown("**Retry Failed Cards**: Safely queues only the 'failed' or 'skipped' cards for another attempt. Ignores successfully processed cards.")
        if st.button("♻️ Queue Failed/Skipped for Retry", type="primary"):
            with engine.begin() as conn:
                # Notice the strict WHERE clause targeting ONLY failures
                retry_query = text("""
                    UPDATE tcg_cards 
                    SET enrichment_status = 'pending'
                    WHERE LOWER(set_id) = :set_id 
                      AND enrichment_status IN ('failed', 'skipped');
                """)
                result = conn.execute(retry_query, {"set_id": selected_set.lower()})
                affected_rows = result.rowcount
                
            if affected_rows > 0:
                st.success(f"✅ Successfully queued {affected_rows} failed/skipped cards back to 'pending'. Click 'Run ML Enrichment' to try them again.")
            else:
                st.info("👍 No failed or skipped cards found in this set!")

# ==========================================
# MODULE 2: DATA LABELER (With Embedded QA)
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
            
        existing_data = {}
        if selected_id in user_history_ids:
            tags_data = user_history[user_history['card_id'] == selected_id].iloc[0].get('tags', {})
            if isinstance(tags_data, str):
                try: tags_data = json.loads(tags_data)
                except: tags_data = {}
            for k in ALL_KEYS: existing_data[k] = bool(tags_data.get(k, 0))

        with st.form(key=f"label_form_{selected_id}", clear_on_submit=False):
            tab_art, tab_aes, tab_feat = st.tabs(["🎨 Art Styles", "✨ Card Aesthetics", "🔍 Card Features"])
            selections = {}
            
            def render_checkboxes(keys, tab_container):
                col_a, col_b = tab_container.columns(2)
                for idx, key in enumerate(keys):
                    display_name = key.replace('_', ' ').title()
                    target_col = col_a if idx % 2 == 0 else col_b
                    selections[key] = target_col.checkbox(display_name, value=existing_data.get(key, False))

            render_checkboxes(ART_STYLE_KEYS, tab_art)
            render_checkboxes(AESTHETIC_KEYS, tab_aes)
            render_checkboxes(BINARY_FEATURES, tab_feat)
            
            st.write("---")
            if st.form_submit_button("💾 Save & Auto-Advance", use_container_width=True, type="primary"):
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
        st.subheader("🎯 Supervised Linear Probe")
        st.markdown("Trains a custom classification layer specifically on your TCG dataset using CLIP embeddings.")
        if st.button("🚀 Train & Test Custom Model", use_container_width=True, type="primary"):
            with st.spinner("Training model and running 80/20 Test Split..."):
                try:
                    result = subprocess.run([sys.executable, "-m", "src.ml.train_model"], capture_output=True, text=True, cwd=PROJECT_ROOT)
                    st.success("Training Complete!")
                    st.text(result.stdout)
                except Exception as e: st.error(f"Error training model: {e}")