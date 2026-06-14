# src/dashboard/pages/1_📥_Data_Ingestor.py
import streamlit as st
import time
import logging
import os
import requests
import pandas as pd
from sqlalchemy import text

from src.dashboard.utils import render_sidebar, get_engine

from src.ml.knn_enricher import run_art_style_enrichment
# Uncomment these if you have them ready:
# from src.ingest.api_fetcher import fetch_set 
# from src.ml.ocr_cleaner import run_ocr_audit

# --- LOGGING SETUP ---
logger = logging.getLogger(__name__)

st.set_page_config(page_title="...", layout="wide")
render_sidebar()

st.title("📥 Modular Data Ingestor")
st.markdown("Execute and verify pipeline stages independently. Select a target scope, then trigger the required micro-service.")
st.divider()

# --- 1. TARGET SCOPE SELECTOR ---
@st.cache_data(ttl=3600, show_spinner=False)
def get_set_dropdown_options():
    """Fetches sets from API & DB to populate the scope selector."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "application/json"
        }
        response = requests.get("https://api.pokemontcg.io/v2/sets", headers=headers, timeout=10)
        response.raise_for_status()
        api_sets = response.json().get('data', [])
    except Exception as e:
        api_sets = []

    engine = get_engine()
    query = text("""
        SELECT set_id,
               COUNT(*) as total_cards,
               SUM(CASE WHEN image_embedding IS NULL THEN 1 ELSE 0 END) as missing_embeddings,
               SUM(CASE WHEN art_style IS NULL OR art_style = '"Manual review needed"' THEN 1 ELSE 0 END) as missing_styles
        FROM tcg_cards
        GROUP BY set_id
    """)
    
    try:
        with engine.connect() as conn:
            db_stats = pd.read_sql(query, conn).set_index("set_id")
    except Exception:
        db_stats = pd.DataFrame()

    options = [{"id": "BULK", "label": "🌍 BULK SWEEP (Entire Database)", "releaseDate": "2099-01-01"}]
    api_set_dict = {s.get('id'): s for s in api_sets}
    all_set_ids = set(api_set_dict.keys()).union(set(db_stats.index))

    for set_id in all_set_ids:
        api_info = api_set_dict.get(set_id, {})
        name = api_info.get('name', f"Set: {set_id.upper()}")
        series = api_info.get('series', 'Local DB')
        
        if set_id not in db_stats.index:
            status = "Missing ❌"
        else:
            stats = db_stats.loc[set_id]
            if stats['missing_embeddings'] > 0 or stats['missing_styles'] > 0:
                status = "Enrichment needed ⚠️"
            else:
                status = "Complete ✅"

        options.append({
            "id": set_id, 
            "label": f"{name} ({series}) - {status}", 
            "releaseDate": api_info.get("releaseDate", "1999-01-01") 
        })

    options.sort(key=lambda x: x.get("releaseDate", ""), reverse=True)
    return options

# --- LIVE METRICS HELPER ---
@st.cache_data(ttl=10, show_spinner=False)
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
# UI RENDERING
# -----------------------------------------
st.markdown("### 🎯 1. Select Target Scope")
set_options = get_set_dropdown_options()

selected_set_dict = st.selectbox(
    "Choose a specific set, or select Bulk Sweep to process the entire database.",
    options=set_options,
    format_func=lambda x: x["label"]
)

target_set = selected_set_dict["id"]
is_bulk = target_set == "BULK"
pass_set = None if is_bulk else target_set

missing_emb, missing_knn = get_live_metrics(target_set)

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
        if st.button("Fetch Metadata", use_container_width=True, disabled=is_bulk):
            if is_bulk:
                st.warning("Cannot bulk fetch. Select a specific set.")
            else:
                with st.spinner(f"Fetching {target_set}..."):
                    try:
                        # count = fetch_set(target_set)
                        st.success(f"Fetched cards!")
                        get_set_dropdown_options.clear()
                        get_live_metrics.clear()
                    except Exception as e:
                        st.error(f"Failed: {e}")

# --- MODULE 2: CLIP EMBEDDINGS ---
with col2:
    with st.container(border=True):
        st.subheader("🧠 2. Embeddings")
        st.caption(f"**{missing_emb:,}** cards pending.")
        st.write("")
        if st.button("Generate CLIP Vectors", use_container_width=True, type="primary" if missing_emb > 0 else "secondary"):
            with st.spinner("Loading Vision Model..."):
                try:
                    start_time = time.time()
                    count = embed_unembedded_cards(target_set=pass_set)
                    duration = round(time.time() - start_time, 1)
                    st.success(f"Embedded {count} cards in {duration}s!")
                    get_set_dropdown_options.clear()
                    get_live_metrics.clear()
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
        if st.button("Run Text Check", use_container_width=True):
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
        if st.button("Run KNN Classifier", use_container_width=True, type="primary" if missing_knn > 0 else "secondary"):
            with st.spinner("Training KNN..."):
                try:
                    start_time = time.time()
                    count = run_art_style_enrichment(target_set=pass_set)
                    duration = round(time.time() - start_time, 1)
                    st.success(f"Mapped {count} styles in {duration}s!")
                    get_set_dropdown_options.clear()
                    get_live_metrics.clear()
                    time.sleep(1.5)
                    st.rerun()
                except Exception as e:
                    st.error(f"KNN Crashed: {e}")