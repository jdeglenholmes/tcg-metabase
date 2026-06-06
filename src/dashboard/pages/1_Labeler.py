import streamlit as st
import pandas as pd
import os
import yaml
import subprocess
import sys
import datetime 
import json
from sqlalchemy import text
from src.database.connection import get_engine

st.set_page_config(page_title="TCG Art Labeler PRO", layout="wide")

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))

# --- TAXONOMIES ---
ART_STYLE_KEYS = [
    "minimalist", "maximalist", "traditional_watercolor", 
    "crisp_digital_portrait", "cinematic", "handcrafted_diorama", "painterly"
]

AESTHETIC_KEYS = [
    "kinetic", "chaotic", "modern", "whimsical", "legendary"
]

ALL_KEYS = ART_STYLE_KEYS + AESTHETIC_KEYS

# --- HELPER FUNCTIONS ---
def run_pipeline_command(cmd_list, step_name):
    log_dir = os.path.join(PROJECT_ROOT, "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "app_log.txt")
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    try:
        result = subprocess.run(
            cmd_list, capture_output=True, text=True, check=True, cwd=PROJECT_ROOT
        )
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"\n[{timestamp}] ✅ SUCCESS: {step_name}\n")
            f.write(result.stdout + "\n")
        return True, result.stdout
    except subprocess.CalledProcessError as e:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"\n[{timestamp}] ❌ ERROR: {step_name} FAILED\n")
            f.write(f"CMD: {' '.join(cmd_list)}\n")
            f.write(f"--- STDOUT ---\n{e.stdout}\n")
            f.write(f"--- STDERR ---\n{e.stderr}\n")
        return False, e.stderr

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

# Enforce Set-by-Set loading (No 'All Sets')
st.sidebar.caption("📂 Select Set")
selected_set = st.sidebar.selectbox("set_select", all_sets, format_func=format_set_name, label_visibility="collapsed")

# --- HIDDEN NUKE PROTOCOL ---
with st.sidebar.expander("☢️ Danger Zone"):
    st.warning(f"Wipe all data for version `{label_version}`?")
    st.caption("Type **NUKE** below to confirm.")
    confirm_nuke = st.text_input("nuke_input", label_visibility="collapsed")
    if confirm_nuke == "NUKE":
        if st.button("🚨 Erase Labels", type="primary", use_container_width=True):
            if os.path.exists(active_csv):
                os.remove(active_csv)
            with engine.begin() as conn:
                # Safely wipe ONLY the manual taxonomies, protecting your ML cameos/embeddings!
                conn.execute(text("UPDATE tcg_cards SET art_style = NULL, card_aesthetic = NULL;"))
            st.success("Slate wiped clean!")
            st.rerun()


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
            
            # --- THIS IS THE PART THAT GOT DELETED! ---
            st.write("---")
            if st.form_submit_button("💾 Save & Auto-Advance", use_container_width=True, type="primary"):
                save_label(selected_id, user_name, target_column, selections, active_csv)
                st.rerun()