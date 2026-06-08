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

st.set_page_config(page_title="TCG Art Labeler PRO", layout="wide")

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))

# --- TAXONOMIES ---
ART_STYLE_KEYS = [
    "minimalist", "maximalist", "traditional_watercolor", 
    "crisp_digital_portrait", "cinematic", "handcrafted_diorama", 
    "surrealist", "standard_generic",
    "pop_art", "comic_book_illustration"
]

AESTHETIC_KEYS = [
    "kinetic", "chaotic", "modern", "whimsical", "legendary", "neutral"
]

BINARY_FEATURES = ["has_cameo", "is_trainer_gallery"]
ALL_KEYS = ART_STYLE_KEYS + AESTHETIC_KEYS + BINARY_FEATURES

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
            if not char and process.poll() is not None:
                break
            
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
        with open("config/sets.yaml", "r") as f:
            config = yaml.safe_load(f)
            raw_yaml_sets = config.get("sets", {})
            
        for readable_slug, set_id in raw_yaml_sets.items():
            if readable_slug.startswith('sv0') or readable_slug == set_id: continue
            clean_name = readable_slug.replace('-', ' ').title()
            if clean_name.endswith(" Gg"): clean_name = clean_name.replace(" Gg", " (Galarian Gallery)")
            if clean_name.endswith(" Tg"): clean_name = clean_name.replace(" Tg", " (Trainer Gallery)")
            mapping[set_id] = clean_name
    except Exception:
        pass
    return mapping, raw_yaml_sets

SET_NAME_MAPPING, RAW_YAML_SETS = get_set_name_mapping()
CHRONOLOGICAL_ORDER = list(RAW_YAML_SETS.values())

def format_set_name(prefix):
    return SET_NAME_MAPPING.get(prefix, prefix.upper())


# --- DATABASE DIRECT CONNECTION ---
def get_labeling_state(selected_set, current_user):
    engine = get_engine()
    
    with engine.connect() as conn:
        # We now pull the new tags and labeled_by columns directly from the database
        query = "SELECT card_id, name, image_url, labeled_by, tags FROM tcg_cards WHERE card_id LIKE :prefix AND image_url IS NOT NULL;"
        db_df = pd.read_sql_query(text(query), conn, params={"prefix": f"{selected_set}-%"})
        
    user_history = pd.DataFrame()
    if not db_df.empty:
        # A card is considered "labeled" if it belongs to the user and has data in the tags column
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
    
    # 1. The Raw Backup (Your new JSONB column)
    tags_json = json.dumps(selections)
    
    # 2. Maintain ML arrays for downstream evaluation
    true_art = [k for k, v in selections.items() if v and k in ART_STYLE_KEYS]
    true_aes = [k for k, v in selections.items() if v and k in AESTHETIC_KEYS]
    
    with engine.begin() as conn:
        query = """
            UPDATE tcg_cards 
            SET tags = :tags,
                labeled_by = :user_name,
                art_style = :art,
                card_aesthetic = :aes,
                updated_at = CURRENT_TIMESTAMP
            WHERE card_id = :card_id;
        """
        conn.execute(text(query), {
            "tags": tags_json, 
            "user_name": user_name,
            "art": json.dumps(true_art), 
            "aes": json.dumps(true_aes),
            "card_id": card_id
        })


# --- HYPER-CLEAN SIDEBAR ---
user_name = st.sidebar.text_input("annotator_name", placeholder="👤 Enter Annotator Name...", label_visibility="collapsed")

if not user_name:
    st.title("TCG Art Labeler")
    st.info("👈 Please enter your annotator name in the sidebar to begin.")
    st.stop()

st.sidebar.write("---")
app_mode = st.sidebar.radio("nav_mode", ["Art Labeler", "Data Manager"], label_visibility="collapsed")
st.sidebar.write("---")

engine = get_engine()
with engine.connect() as conn:
    set_query = "SELECT DISTINCT split_part(card_id, '-', 1) as set_prefix FROM tcg_cards;"
    raw_db_sets = [r[0] for r in conn.execute(text(set_query)).fetchall() if r[0]]
    
all_sets = sorted(raw_db_sets, key=lambda x: CHRONOLOGICAL_ORDER.index(x) if x in CHRONOLOGICAL_ORDER else 9999)

# Enforce Set-by-Set loading
st.sidebar.caption("📂 Select Set")
selected_set = st.sidebar.selectbox("set_select", all_sets, format_func=format_set_name, label_visibility="collapsed")


# ==========================================
# MODE 1: STANDARD LABELING 
# ==========================================
if app_mode == "Art Labeler":
    st.title(f"📂 {format_set_name(selected_set)}")
    
    # 💥 CSV IS GONE! We only query the database now.
    db_df, user_history = get_labeling_state(selected_set, user_name)
    
    if db_df.empty:
        st.warning("No cards found for this set. Please run Ingestion in the Data Manager!")
        st.stop()
        
    user_history_ids = user_history['card_id'].values if not user_history.empty else []
    display_map = {}
    for _, row in db_df.iterrows():
        num = row['card_id'].split('-')[-1]
        flag = "✅ " if row['card_id'] in user_history_ids else ""
        display_map[row['card_id']] = f"{flag}{row['name']} / {num}"
    
    nav_col1, nav_col2, nav_col3 = st.columns([2, 1, 1])
    with nav_col1:
        card_list = db_df['card_id'].tolist()
        
        if "nav_selectbox" in st.session_state and st.session_state["nav_selectbox"] not in card_list:
            del st.session_state["nav_selectbox"]
            
        if "advance_to" in st.session_state:
            if st.session_state["advance_to"] in card_list:
                st.session_state["nav_selectbox"] = st.session_state["advance_to"]
            del st.session_state["advance_to"]
            
        elif "nav_selectbox" not in st.session_state:
            unlabeled_df = db_df[~db_df['card_id'].isin(user_history_ids)]
            if not unlabeled_df.empty:
                st.session_state["nav_selectbox"] = unlabeled_df.iloc[0]['card_id']
            else:
                st.session_state["nav_selectbox"] = card_list[0]
                
        selected_id = st.selectbox(
            "card_nav", 
            options=card_list,
            format_func=lambda x: display_map[x],
            key="nav_selectbox", 
            label_visibility="collapsed"
        )
        current_card = db_df[db_df['card_id'] == selected_id].iloc[0]

    total_labeled = len(user_history)
    set_labeled = len(user_history[user_history['card_id'].str.startswith(f"{selected_set}-")]) if total_labeled > 0 else 0
    
    with nav_col2:
        st.metric("Set Progress", f"{set_labeled} / {len(db_df)}")
    with nav_col3:
        st.metric("Total User Labels", total_labeled)
        
    st.write("---")
        
    col1, col2 = st.columns([1, 2]) 
    
    with col1:
        st.image(current_card['image_url'], use_container_width=True)
        
    with col2:
        # Safely extract the JSON data directly from the PostgreSQL row
        existing_data = {}
        if selected_id in user_history_ids:
            existing_row = user_history[user_history['card_id'] == selected_id].iloc[0]
            tags_data = existing_row.get('tags')
            
            # Handle empty states securely
            if pd.isna(tags_data):
                tags_data = {}
            elif isinstance(tags_data, str):
                try:
                    tags_data = json.loads(tags_data)
                except:
                    tags_data = {}
                    
            for k in ALL_KEYS:
                existing_data[k] = bool(tags_data.get(k, 0))

        with st.form(key=f"label_form_{selected_id}", clear_on_submit=False):
            
            tab_art, tab_aes, tab_feat = st.tabs(["🎨 Art Styles", "✨ Card Aesthetics", "🔍 Card Features"])
            selections = {}
            
            def render_checkboxes(keys, tab_container):
                col_a, col_b = tab_container.columns(2)
                for idx, key in enumerate(keys):
                    display_name = key.replace('_', ' ').title()
                    default_val = existing_data.get(key, False)
                    target_col = col_a if idx % 2 == 0 else col_b
                    selections[key] = target_col.checkbox(display_name, value=default_val)

            render_checkboxes(ART_STYLE_KEYS, tab_art)
            render_checkboxes(AESTHETIC_KEYS, tab_aes)
            render_checkboxes(BINARY_FEATURES, tab_feat)
            
            st.write("---")
            
            if st.form_submit_button("💾 Save & Auto-Advance", use_container_width=True, type="primary"):
                
                # Direct Database Injection 
                save_label_to_db(selected_id, user_name, selections)
                
                current_idx = card_list.index(selected_id)
                if current_idx + 1 < len(card_list):
                    st.session_state["advance_to"] = card_list[current_idx + 1]
                
                st.rerun()
                
# ==========================================
# MODE 2: DATA MANAGER & INGESTION 
# ==========================================
elif app_mode == "Data Manager":
    st.title("🗄️ Database Manager")
    st.write("Track ingestion progress and enrich sets with machine learning metadata.")
    
    engine = get_engine()
    with engine.connect() as conn:
        count_query = """
            SELECT 
                LOWER(set_id) as set_prefix, 
                COUNT(*) as total_cards,
                COUNT(CASE WHEN enrichment_status = 'processed' THEN 1 END) as enriched_cards
            FROM tcg_cards 
            GROUP BY LOWER(set_id);
        """
        db_stats = {r[0]: {'total': r[1], 'enriched': r[2]} for r in conn.execute(text(count_query)).fetchall()}
        
    yaml_canonical_ids = list(RAW_YAML_SETS.values())
    sorted_yaml_sets = sorted(yaml_canonical_ids, key=lambda x: CHRONOLOGICAL_ORDER.index(x) if x in CHRONOLOGICAL_ORDER else 9999)
    
    def format_manager_option(set_id):
        name = format_set_name(set_id)
        stats = db_stats.get(set_id, {'total': 0, 'enriched': 0})
        
        if stats['total'] == 0:
            return f"🔴 {name}  [Missing]"
        elif stats['enriched'] < stats['total']:
            return f"🟡 {name}  [{stats['enriched']}/{stats['total']} Enriched]"
        else:
            return f"🟢 {name}  [{stats['total']} cards - Fully Ready]"
    
    st.write("---")
    st.subheader("Database Actions")
    
    target_set = st.selectbox(
        "Select a Target Set:", 
        options=sorted_yaml_sets, 
        format_func=format_manager_option
    )
    
    st.write("---")
    
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("📥 1. Ingest Raw API Data", use_container_width=True):
            reverse_yaml = {v: k for k, v in RAW_YAML_SETS.items()}
            slug_to_ingest = reverse_yaml.get(target_set, target_set)
            
            ingest_cmd = [sys.executable, "-m", "src.ingest.run", "--ingest", "--set_name", slug_to_ingest]
            success, output = run_pipeline_live(ingest_cmd, f"Ingesting Set: {format_set_name(target_set)}")
            
            if success:
                st.toast("Ingestion Complete! Ready for Enrichment.", icon="✅")
                st.rerun()
            else:
                st.error("Ingestion failed. Check logs.")
                
    with col2:
        if st.button("🧠 2. Run ML Enrichment", use_container_width=True, type="primary"):
            enrich_cmd = [
                sys.executable, "-m", "src.ingest.run", 
                "--enrich", 
                "--set_name", target_set 
            ]
            success, output = run_pipeline_live(enrich_cmd, f"Enriching {format_set_name(target_set)}...")
            
            if success:
                st.toast("Enrichment Complete!", icon="✅")
                st.rerun()

    # ==========================================
    # NEW ADDITION: Advanced Set Maintenance
    # ==========================================
    st.write("---")
    with st.expander("⚠️ Advanced Set Maintenance", expanded=False):
        st.warning(f"**Danger Zone:** These actions will modify existing records for **{format_set_name(target_set)}**.")
        
        st.markdown("""
        **Reset ML Enrichment**
        If you have updated the CLIP model or changed the taxonomy, use this to clear the machine predictions for this set. This allows the enrichment pipeline to process the set again from scratch. *(Note: This does NOT delete your human tags).*
        """)
        
        if st.button("🔄 Reset Enrichment Status", type="secondary"):
            with engine.begin() as conn:
                # Clear the ML predictions and status, but leave the human 'tags' intact
                reset_query = text("""
                    UPDATE tcg_cards 
                    SET enrichment_status = 'pending',
                        art_style = NULL,
                        card_aesthetic = NULL,
                        image_embedding = NULL
                    WHERE LOWER(set_id) = :set_id;
                """)
                conn.execute(reset_query, {"set_id": target_set.lower()})
                
            st.success(f"✅ Reset complete! {format_set_name(target_set)} is ready to be re-enriched.")
            st.rerun()