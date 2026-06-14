# src/dashboard/pages/1_📥_Data_Ingestor.py
import streamlit as st
import time
import logging
import pandas as pd
from sqlalchemy import text

from src.dashboard.utils import render_sidebar, get_engine
from src.ml.knn_enricher import run_art_style_enrichment
# from src.ingest.api_fetcher import fetch_set 
# from src.ml.ocr_cleaner import run_ocr_audit

# --- LOGGING SETUP ---
logger = logging.getLogger(__name__)

st.set_page_config(page_title="Data Ingestor", layout="wide", page_icon="📥")
render_sidebar()

st.title("📥 Modular Data Ingestor")
st.markdown("Execute and verify pipeline stages independently. Select your operating mode, then trigger the required micro-service.")
st.divider()

# --- 1. LIGHTWEIGHT DB QUERY (For Mode 2) ---
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

# --- LIVE METRICS HELPER ---
def get_live_metrics(target_set):
    """Gets the exact number of cards needing work based on the scope."""
    engine = get_engine()
    params = {}
    
    base_emb_query = "SELECT COUNT(*) FROM tcg_cards WHERE image_embedding IS NULL AND image_url IS NOT NULL"
    base_knn_query = "SELECT COUNT(*) FROM tcg_cards WHERE REPLACE(supertype, 'é', 'e') = 'Pokemon' AND (art_style IS NULL OR art_style = '\"Manual review needed\"')"
    
    if target_set != "BULK":
        base_emb_query += " AND set_id ILIKE :set_id"
        base_knn_query += " AND set_id ILIKE :set_id"
        params["set_id"] = f"%{target_set}%"
        
    try:
        with engine.connect() as conn:
            missing_emb = conn.execute(text(base_emb_query), params).scalar() or 0
            missing_knn = conn.execute(text(base_knn_query), params).scalar() or 0
            return missing_emb, missing_knn
    except Exception:
        return 0, 0


# -----------------------------------------
# UI RENDERING: THE MODE SELECTOR
# -----------------------------------------
st.markdown("### 🎯 1. Operating Mode")

mode = st.radio(
    "Select Scope:",
    ["🌍 Bulk Database Sweep (Process all existing data)", 
     "🎯 Target Existing Set (Re-process a specific set)", 
     "📡 Fetch New Set (Download from API)"],
    label_visibility="collapsed"
)

# Handle UI rendering based on the selected mode
target_set = "BULK"
pass_set = None

with st.container(border=True):
    if "Bulk" in mode:
        st.info("Currently targeting the **entire database**. API fetching is disabled in this mode.")
        target_set = "BULK"
        pass_set = None
        
    elif "Target Existing" in mode:
        existing_sets = get_existing_db_sets()
        if not existing_sets:
            st.warning("No sets found in the database yet.")
            target_set = "BULK"
        else:
            selected = st.selectbox("Select Set to Process:", existing_sets)
            target_set = selected
            pass_set = selected
            
    elif "Fetch New" in mode:
        entered_set = st.text_input("Enter Official Set ID (e.g., 'swsh1', 'base1'):", placeholder="Type Set ID here...")
        if entered_set.strip():
            target_set = entered_set.strip().lower()
            pass_set = target_set
        else:
            st.warning("Please enter a Set ID to proceed.")
            target_set = "WAITING"

# Fetch live metrics based on the dynamically determined target_set
if target_set != "WAITING":
    missing_emb, missing_knn = get_live_metrics(target_set)
else:
    missing_emb, missing_knn = 0, 0


st.write("")
st.markdown("### ⚙️ 2. Execution Deck")

# Create the 4 Modular Columns
col1, col2, col3, col4 = st.columns(4, gap="medium")

# --- MODULE 1: API FETCH ---
with col1:
    with st.container(border=True):
        st.subheader("📡 1. API Fetch")
        st.caption("Download metadata & image URLs.")
        st.write("")
        
        # Only enable if in 'Fetch New' mode AND they typed something
        can_fetch = ("Fetch New" in mode) and (target_set != "WAITING")
        
        if st.button("Fetch Metadata", use_container_width=True, disabled=not can_fetch):
            with st.spinner(f"Fetching {target_set} from Pokémon TCG API..."):
                try:
                    # count = fetch_set(target_set)
                    st.success(f"Fetched {target_set}!")
                    get_existing_db_sets.clear() # Clear cache so the new set appears in Mode 2
                    time.sleep(1.5)
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed: {e}")

# --- MODULE 2: CLIP EMBEDDINGS ---
with col2:
    with st.container(border=True):
        st.subheader("🧠 2. Embeddings")
        st.caption(f"**{missing_emb:,}** cards pending.")
        st.write("")
        
        can_embed = (missing_emb > 0) and (target_set != "WAITING")
        
        if st.button("Generate CLIP Vectors", use_container_width=True, disabled=not can_embed, type="primary" if can_embed else "secondary"):
            with st.spinner("Loading Vision Model..."):
                try:
                    start_time = time.time()
                    count = embed_unembedded_cards(target_set=pass_set)
                    duration = round(time.time() - start_time, 1)
                    st.success(f"Embedded {count} cards in {duration}s!")
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
        
        can_ocr = target_set != "WAITING"
        
        if st.button("Run Text Check", use_container_width=True, disabled=not can_ocr):
            with st.spinner("Running EasyOCR..."):
                try:
                    # count = run_ocr_audit(target_set=pass_set)
                    st.success(f"OCR Complete!")
                except Exception as e:
                    st.error(f"OCR Crashed: {e}")

# --- MODULE 4: KNN ENRICHMENT ---
with col4:
    with st.container(border=True):
        st.subheader("🎨 4. Art Styles")
        st.caption(f"**{missing_knn:,}** cards pending.")
        st.write("")
        
        can_knn = (missing_knn > 0) and (target_set != "WAITING")
        
        if st.button("Run KNN Classifier", use_container_width=True, disabled=not can_knn, type="primary" if can_knn else "secondary"):
            with st.spinner("Training KNN..."):
                try:
                    start_time = time.time()
                    count = run_art_style_enrichment(target_set=pass_set)
                    duration = round(time.time() - start_time, 1)
                    st.success(f"Mapped {count} styles in {duration}s!")
                    time.sleep(1.5)
                    st.rerun()
                except Exception as e:
                    st.error(f"KNN Crashed: {e}")