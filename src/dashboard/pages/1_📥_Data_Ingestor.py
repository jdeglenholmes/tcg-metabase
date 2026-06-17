# src/dashboard/pages/1_📥_Data_Ingestor.py
import streamlit as st
import time
import sys
import subprocess
import logging
import requests
import pandas as pd
from sqlalchemy import text

from src.dashboard.utils import render_sidebar, get_engine

# --- LOGGING SETUP ---
logger = logging.getLogger(__name__)

st.set_page_config(page_title="Data Ingestor", layout="wide", page_icon="📥")
render_sidebar()

st.title("📥 Modular Data Ingestor")
st.markdown("Execute and verify pipeline stages independently. Select your operating mode, then trigger the required micro-service.")

# ==========================================
# 1. INTELLIGENT DATA MAPPING (Zero-Maintenance)
# ==========================================
@st.cache_data(ttl=86400, show_spinner=False) 
def get_official_catalog():
    """Fetches the official master list of all sets and series from the API."""
    try:
        headers = {
            "User-Agent": "TCG-ML-Studio/1.0", # Honest app declaration
            "Accept": "application/json"
        }
        response = requests.get("https://api.pokemontcg.io/v2/sets", headers=headers, timeout=10)
        response.raise_for_status() 
        api_sets = response.json().get('data', [])
        
        catalog = {}
        for s in api_sets:
            catalog[s['id']] = {
                "name": s['name'],
                "series": s['series'],
                "releaseDate": s.get('releaseDate', '1999-01-01')
            }
        return catalog
    except Exception as e:
        logger.error(f"Failed to fetch catalog: {e}")
        return {}

@st.cache_data(ttl=60, show_spinner=False)
def get_existing_db_sets():
    """Quickly fetches only the sets that currently exist in your database."""
    engine = get_engine()
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT DISTINCT set_id FROM tcg_cards WHERE set_id IS NOT NULL")).fetchall()
            return [row[0] for row in result]
    except Exception:
        return []

catalog = get_official_catalog()
db_sets = get_existing_db_sets()

# ==========================================
# 2. GAP ANALYSIS METRICS
# ==========================================
official_set_ids = set()
db_set_ids = set(db_sets)
missing_sets = set()
missing_series = set()

if catalog:
    official_set_ids = set(catalog.keys())
    missing_sets = official_set_ids - db_set_ids
    
    official_series = set(data['series'] for data in catalog.values())
    db_series = set(catalog[sid]['series'] for sid in db_set_ids if sid in catalog)
    missing_series = official_series - db_series

    with st.expander("📊 View Pipeline Ingestion Gaps", expanded=False):
        c1, c2, c3 = st.columns(3)
        c1.metric("Total Ingested Sets", f"{len(db_set_ids)} / {len(official_set_ids)}")
        c2.metric("Missing Sets", len(missing_sets))
        c3.metric("Missing Series entirely", len(missing_series))
        
        if missing_series:
            st.caption("**Series completely missing from DB:**")
            st.write(", ".join(sorted(list(missing_series))))
else:
    st.warning("⚠️ Could not reach Pokémon TCG API to calculate gaps.")

st.divider()

# ==========================================
# 3. LIVE DB METRICS HELPER
# ==========================================
def get_live_metrics(target_set_list):
    """Gets exact number of cards needing work."""
    if not target_set_list:
        return 0, 0
        
    engine = get_engine()
    params = {}
    
    base_emb = "SELECT COUNT(*) FROM tcg_cards WHERE image_embedding IS NULL AND image_url IS NOT NULL"
    base_knn = "SELECT COUNT(*) FROM tcg_cards WHERE REPLACE(supertype, 'é', 'e') = 'Pokemon' AND (art_style IS NULL OR art_style = '\"Manual review needed\"')"
    
    if target_set_list != ["BULK"]:
        in_clause = " AND set_id IN (" + ", ".join([f":s_{i}" for i in range(len(target_set_list))]) + ")"
        base_emb += in_clause
        base_knn += in_clause
        for i, sid in enumerate(target_set_list):
            params[f"s_{i}"] = sid
            
    try:
        with engine.connect() as conn:
            missing_emb = conn.execute(text(base_emb), params).scalar() or 0
            missing_knn = conn.execute(text(base_knn), params).scalar() or 0
            return missing_emb, missing_knn
    except Exception:
        return 0, 0

# ==========================================
# 4. MODE SELECTOR & WATERFALL UX
# ==========================================
st.markdown("### 🎯 1. Operating Mode")

if "ingestor_mode" not in st.session_state:
    st.session_state.ingestor_mode = "🌍 Bulk Database Sweep (Process all existing data)"
if "last_fetched" not in st.session_state:
    st.session_state.last_fetched = []

# --- THE FIX: Apply pending mode changes BEFORE the widget renders ---
if "pending_mode_switch" in st.session_state:
    st.session_state.ingestor_mode = st.session_state.pop("pending_mode_switch")

mode = st.radio(
    "Select Scope:",
    ["🌍 Bulk Database Sweep (Process all existing data)", 
     "🎯 Target Existing Data (Re-process specific sets)", 
     "📡 Fetch New Data (Download from API)"],
    label_visibility="collapsed",
    key="ingestor_mode" 
)

target_sets_to_process = [] 
fetch_queue = [] 
fetch_label = ""

with st.container(border=True):
    if "Bulk Database" in mode:
        st.info("Currently targeting the **entire database**. API fetching is disabled in this mode.")
        target_sets_to_process = ["BULK"]
        
    elif "Target Existing" in mode:
        if not db_sets:
            st.warning("No sets found in the database yet.")
        else:
            valid_defaults = [s for s in st.session_state.last_fetched if s in db_sets]
            
            selected_sets = st.multiselect(
                "Select Existing Sets to Process:", 
                db_sets,
                default=valid_defaults if valid_defaults else None,
                format_func=lambda x: f"{catalog[x]['name']} ({catalog[x]['series']})" if x in catalog else x,
                key="multi_select_existing"
            )
            target_sets_to_process = selected_sets
            
    elif "Fetch New Data" in mode:
        fetch_type = st.radio("Fetch By:", ["Target a Specific Series", "Target a Specific Set"], horizontal=True, key="fetch_by_radio")
        
        if "Series" in fetch_type:
            series_with_missing_sets = sorted(list({catalog[sid]['series'] for sid in missing_sets}))
            if not series_with_missing_sets:
                st.success("You have ingested every series! Nothing to fetch.")
            else:
                selected_series = st.selectbox("Select Series to Download:", series_with_missing_sets, key="series_select")
                fetch_queue = [s for s in missing_sets if catalog[s]['series'] == selected_series]
                fetch_queue.sort(key=lambda x: catalog[x]['releaseDate'])
                
                fetch_label = f"Fetch {len(fetch_queue)} Sets in '{selected_series}'"
                st.caption(f"**Sets to download:** {', '.join([catalog[s]['name'] for s in fetch_queue])}")
                
        else:
            if not missing_sets:
                st.success("You have ingested every set! Nothing to fetch.")
            else:
                sorted_missing = sorted(list(missing_sets), key=lambda x: (catalog[x]['series'], catalog[x]['releaseDate']))
                selected = st.selectbox(
                    "Select Missing Set to Download:", 
                    sorted_missing,
                    format_func=lambda x: f"{catalog[x]['name']} ({catalog[x]['series']})",
                    key="set_select"
                )
                fetch_queue = [selected]
                fetch_label = f"Fetch '{catalog[selected]['name']}'"

if "Fetch New Data" not in mode:
    missing_emb, missing_knn = get_live_metrics(target_sets_to_process)
else:
    missing_emb, missing_knn = 0, 0

st.write("")
st.markdown("### ⚙️ 2. Execution Deck")

col1, col2, col3, col4 = st.columns(4, gap="medium")

# --- MODULE 1: API FETCH ---
with col1:
    with st.container(border=True):
        st.subheader("📡 1. API Fetch")
        st.caption("Download metadata & images.")
        st.write("")
        
        can_fetch = ("Fetch New Data" in mode) and (len(fetch_queue) > 0)
        
        if st.button(fetch_label if can_fetch else "Fetch Metadata", use_container_width=True, disabled=not can_fetch, type="primary" if can_fetch else "secondary", key="btn_fetch"):
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            try:
                for i, s_id in enumerate(fetch_queue):
                    set_name = catalog[s_id]['name']
                    status_text.write(f"Fetching {set_name} ({i+1}/{len(fetch_queue)})...")
                    
                    subprocess.run(
                        [sys.executable, "src/ingest/run.py", "--ingest", "--set_name", s_id], 
                        check=True
                    )
                    progress_bar.progress((i + 1) / len(fetch_queue))
                    
                st.success(f"Successfully fetched!")
                
                # WATERFALL UX TRIGGER: Switch mode and auto-select your newly downloaded sets
                st.session_state.last_fetched = fetch_queue
                st.session_state.pending_mode_switch = "🎯 Target Existing Data (Re-process specific sets)"
                get_existing_db_sets.clear() 
                time.sleep(1)
                st.rerun()
                
            except Exception as e:
                st.error(f"Failed: {e}")

# --- MODULE 2: CLIP EMBEDDINGS ---
with col2:
    with st.container(border=True):
        st.subheader("🧠 2. Embeddings")
        st.caption(f"**{missing_emb:,}** cards pending.")
        st.write("")
        
        can_embed = (missing_emb > 0) 
        
        if st.button("Generate Vectors", use_container_width=True, disabled=not can_embed, type="primary" if can_embed else "secondary", key="btn_embed"):
            
            # --- NEW: Live terminal log window ---
            log_output = st.empty() 
            
            with st.spinner("Running background worker..."):
                try:
                    start_time = time.time()
                    process_list = target_sets_to_process if target_sets_to_process != ["BULK"] else [None]
                    
                    for i, s_id in enumerate(process_list):
                        cmd = [sys.executable, "src/ingest/run.py", "--enrich"]
                        if s_id: 
                            cmd.extend(["--set_name", s_id])
                        
                        # Use Popen to intercept the background process output
                        process = subprocess.Popen(
                            cmd, 
                            stdout=subprocess.PIPE, 
                            stderr=subprocess.STDOUT, 
                            text=True,
                            bufsize=1
                        )
                        
                        # Stream each line to the Streamlit UI as it happens
                        for line in process.stdout:
                            log_output.code(line.strip(), language="bash")
                            
                        process.wait()
                        
                        if process.returncode != 0:
                            raise Exception(f"Worker crashed with exit code {process.returncode}")
                        
                    duration = round(time.time() - start_time, 1)
                    st.success(f"Embedded vectors in {duration}s!")
                    time.sleep(1.5)
                    st.rerun()
                except Exception as e:
                    st.error(f"Embedder Crashed: {e}")

# --- MODULE 3: OCR AUDIT ---
with col3:
    with st.container(border=True):
        st.subheader("👁️ 3. OCR Audit")
        st.caption("Verify physical card text.")
        st.write("")
        
        can_ocr = (len(target_sets_to_process) > 0)
        
        if st.button("Run Text Check", use_container_width=True, disabled=not can_ocr, key="btn_ocr"):
            with st.spinner("Loading EasyOCR & Scanning..."):
                try:
                    start_time = time.time()
                    process_list = target_sets_to_process if target_sets_to_process != ["BULK"] else [None]
                    
                    for s_id in process_list:
                        # Construct subprocess call to the new run.py --ocr flag
                        cmd = [sys.executable, "src/ingest/run.py", "--ocr"]
                        if s_id: 
                            cmd.extend(["--set_name", s_id])
                        
                        subprocess.run(cmd, check=True)
                        
                    duration = round(time.time() - start_time, 1)
                    st.success(f"OCR Audit finished in {duration}s!")
                    time.sleep(1.5)
                    st.rerun()
                except Exception as e:
                    st.error(f"OCR Crashed: {e}")

# --- MODULE 4: KNN ENRICHMENT ---
with col4:
    with st.container(border=True):
        st.subheader("🎨 4. Art Styles")
        st.caption(f"**{missing_knn:,}** cards pending.")
        st.write("")
        
        can_knn = (missing_knn > 0) 
        
        if st.button("Run KNN Classifier", use_container_width=True, disabled=not can_knn, type="primary" if can_knn else "secondary", key="btn_knn"):
            with st.spinner("Training KNN..."):
                try:
                    start_time = time.time()
                    process_list = target_sets_to_process if target_sets_to_process != ["BULK"] else [None]
                    
                    for s_id in process_list:
                        # Construct subprocess call to your run.py --enrich flag
                        # Ensure your run.py handles --enrich correctly now!
                        cmd = [sys.executable, "src/ingest/run.py", "--knn"]
                        if s_id: 
                            cmd.extend(["--set_name", s_id])
                        
                        subprocess.run(cmd, check=True)
                        
                    duration = round(time.time() - start_time, 1)
                    st.success(f"Mapped art styles in {duration}s!")
                    time.sleep(1.5)
                    st.rerun()
                except Exception as e:
                    st.error(f"KNN Crashed: {e}")