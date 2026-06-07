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
    "painterly", "standard_generic", "other_unique" 
]

AESTHETIC_KEYS = [
    "kinetic", "chaotic", "modern", "whimsical", "legendary", "neutral"
]

ALL_KEYS = ART_STYLE_KEYS + AESTHETIC_KEYS

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
        # We use STDOUT and STDERR combined, as tqdm writes to STDERR by default
        process = subprocess.Popen(
            cmd_list, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
            text=True, cwd=PROJECT_ROOT, bufsize=1, encoding='utf-8'
        )
        
        output_lines = []
        current_line = ""
        
        # Read character by character to accurately capture tqdm's \r (carriage return) carriage updates
        while True:
            char = process.stdout.read(1)
            if not char and process.poll() is not None:
                break
            
            if char in ['\r', '\n']:
                clean_line = current_line.strip()
                if clean_line:
                    # Look for the tqdm percentage (e.g., "45%|")
                    match = re.search(r'(\d{1,3})%\|', clean_line)
                    if match:
                        pct = min(int(match.group(1)), 100)
                        progress_bar.progress(pct / 100.0)
                        
                    # Update the live status text with the current operation
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

def init_csv(csv_path):
    if not os.path.exists(csv_path):
        df = pd.DataFrame(columns=["card_id", "labeled_by"] + ALL_KEYS)
        df.to_csv(csv_path, index=False)
    else:
        df = pd.read_csv(csv_path)
        missing_cols = [col for col in ALL_KEYS if col not in df.columns]
        if missing_cols:
            for col in missing_cols:
                df[col] = 0
            df.to_csv(csv_path, index=False)

def get_labeling_state(selected_set, current_user, csv_path):
    init_csv(csv_path)
    labelled_df = pd.read_csv(csv_path)
    
    user_history = pd.DataFrame()
    if not labelled_df.empty and 'labeled_by' in labelled_df.columns:
        user_history = labelled_df[labelled_df['labeled_by'] == current_user]
    
    engine = get_engine()
    with engine.connect() as conn:
        query = "SELECT card_id, name, image_url FROM tcg_cards WHERE card_id LIKE :prefix AND image_url IS NOT NULL;"
        db_df = pd.read_sql_query(text(query), conn, params={"prefix": f"{selected_set}-%"})
        
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

def save_label(card_id, user_name, target_column, selections, csv_path):
    df = pd.read_csv(csv_path)
    mask = (df['card_id'] == card_id) & (df['labeled_by'] == user_name)
    row_data = {"card_id": card_id, "labeled_by": user_name}
    
    if mask.any():
        existing_row = df[mask].iloc[0].to_dict()
        for k in ALL_KEYS:
            row_data[k] = existing_row.get(k, 0)
    else:
        for k in ALL_KEYS:
            row_data[k] = 0
            
    for key, val in selections.items():
        row_data[key] = 1 if val else 0
        
    df = df[~mask]
    df = pd.concat([df, pd.DataFrame([row_data])], ignore_index=True)
    df.to_csv(csv_path, index=False)
    
    true_labels = [k for k, v in selections.items() if v]
    engine = get_engine()
    with engine.begin() as conn:
        query = f"""
            UPDATE tcg_cards 
            SET {target_column} = :labels,
                updated_at = CURRENT_TIMESTAMP
            WHERE card_id = :card_id;
        """
        conn.execute(text(query), {"labels": json.dumps(true_labels), "card_id": card_id})


# --- HYPER-CLEAN SIDEBAR ---
user_name = st.sidebar.text_input("annotator_name", placeholder="👤 Enter Annotator Name...", label_visibility="collapsed")

if not user_name:
    st.title("TCG Art Labeler")
    st.info("👈 Please enter your annotator name in the sidebar to begin.")
    st.stop()

# Version Control
st.sidebar.caption("🏷️ Labeling Version")
label_version = st.sidebar.text_input("version", value="v1", label_visibility="collapsed")
active_csv = f"ground_truth_{label_version}.csv"

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
    
    db_df, user_history = get_labeling_state(selected_set, user_name, active_csv)
    
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
        unlabeled_df = db_df[~db_df['card_id'].isin(user_history_ids)]
        default_idx = 0
        if not unlabeled_df.empty:
            first_unlabeled_id = unlabeled_df.iloc[0]['card_id']
            default_idx = db_df['card_id'].tolist().index(first_unlabeled_id)
        
        selected_id = st.selectbox(
            "card_nav", 
            options=db_df['card_id'].tolist(),
            format_func=lambda x: display_map[x],
            index=default_idx,
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
        taxonomy_choice = st.radio(
            "target_toggle", 
            ["🎨 Art Styles", "✨ Card Aesthetics"], 
            horizontal=True,
            label_visibility="collapsed"
        )
        
        if taxonomy_choice == "🎨 Art Styles":
            current_keys = ART_STYLE_KEYS
            target_column = "art_style"
        else:
            current_keys = AESTHETIC_KEYS
            target_column = "card_aesthetic"
            
        existing_data = {}
        if selected_id in user_history_ids:
            existing_row = user_history[user_history['card_id'] == selected_id].iloc[0]
            for k in current_keys:
                existing_data[k] = bool(existing_row.get(k, 0))
        
        with st.form(key=f"label_form_{selected_id}_{target_column}", clear_on_submit=False):
            selections = {}
            form_col1, form_col2 = st.columns(2)
            
            for idx, key in enumerate(current_keys):
                display_name = key.replace('_', ' ').title()
                default_val = existing_data.get(key, False)
                
                if idx % 2 == 0:
                    selections[key] = form_col1.checkbox(display_name, value=default_val)
                else:
                    selections[key] = form_col2.checkbox(display_name, value=default_val)
            
            st.write("---")
            if st.form_submit_button("💾 Save & Auto-Advance", use_container_width=True, type="primary"):
                save_label(selected_id, user_name, target_column, selections, active_csv)
                st.rerun()

# ==========================================
# MODE 2: DATA MANAGER & INGESTION 
# ==========================================
elif app_mode == "Data Manager":
    st.title("🗄️ Database Manager")
    st.write("Track ingestion progress and enrich sets with machine learning metadata.")
    
    engine = get_engine()
    with engine.connect() as conn:
        # FIX: Use LOWER(set_id) instead of split_part string manipulation
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
    
    # Split the actions into two distinct buttons
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
            # Pass the current target_set to the enrich command
            enrich_cmd = [
                sys.executable, "-m", "src.ingest.run", 
                "--enrich", 
                "--set_name", target_set # <--- PASS THE SET NAME HERE
            ]
            success, output = run_pipeline_live(enrich_cmd, f"Enriching {format_set_name(target_set)}...")
            
            if success:
                st.toast("Enrichment Complete!", icon="✅")
                st.rerun()