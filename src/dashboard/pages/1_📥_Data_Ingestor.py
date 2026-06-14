# src/dashboard/pages/1_📥_Data_Ingestor.py
import streamlit as st
import time
import logging
import os
import requests
import pandas as pd
from sqlalchemy import text

from src.dashboard.utils import render_sidebar, get_engine
from src.pipeline.master_pipeline import run_end_to_end_pipeline

# --- LOGGING SETUP ---
os.makedirs('logs', exist_ok=True)
logging.basicConfig(
    filename='logs/app_log.txt',
    level=logging.DEBUG, # <-- CHANGED FROM INFO TO DEBUG
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

st.set_page_config(page_title="Data Pipeline", layout="wide", page_icon="📥")
user_name, _ = render_sidebar()

st.title("📥 Master Data Engineering Pipeline")
st.markdown("Orchestrate the complete ETL and ML Enrichment process for the Pokémon TCG database.")
st.divider()

# --- HELPER: FETCH SET STATUSES (BULLETPROOF VERSION) ---
@st.cache_data(ttl=3600, show_spinner=False)
def get_set_dropdown_options():
    """Fetches sets from API & DB, providing a resilient merged list."""
    
    # 1. Fetch from API using a full, unblockable Chrome User-Agent
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "application/json"
        }
        # If you registered an API key in your previous builds, uncomment this:
        # headers["X-Api-Key"] = "YOUR_API_KEY_HERE"
        
        response = requests.get("https://api.pokemontcg.io/v2/sets", headers=headers, timeout=10)
        response.raise_for_status()
        api_sets = response.json().get('data', [])
    except Exception as e:
        logger.error(f"Failed to fetch sets from API: {e}")
        api_sets = []

    # 2. Query Local Database for what already exists locally
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
    except Exception as e:
        logger.error(f"Database query failed: {e}")
        db_stats = pd.DataFrame()

    # 3. Merge API data with Local Database stats safely
    options = []
    api_set_dict = {s.get('id'): s for s in api_sets}
    
    # Create a union of sets found in the API AND sets found in your local database
    all_set_ids = set(api_set_dict.keys()).union(set(db_stats.index))

    for set_id in all_set_ids:
        api_info = api_set_dict.get(set_id, {})
        # If API failed, fallback to raw DB names
        name = api_info.get('name', f"Set: {set_id.upper()}")
        series = api_info.get('series', 'Local Database Set')
        
        if set_id not in db_stats.index:
            status = "Missing ❌"
        else:
            stats = db_stats.loc[set_id]
            if stats['missing_embeddings'] > 0 or stats['missing_styles'] > 0:
                status = "Enrichment needed ⚠️"
            else:
                status = "Ingested and enriched ✅"

        label = f"{name} ({series}) - {status}"
        options.append({
            "id": set_id, 
            "label": label, 
            "releaseDate": api_info.get("releaseDate", "1999-01-01") 
        })

    # Sort so newest sets are at the top
    options.sort(key=lambda x: x.get("releaseDate", ""), reverse=True)
    return options

    # --- HELPER: FETCH BULK METRICS ---
@st.cache_data(ttl=60, show_spinner=False)
def get_pending_bulk_counts():
    """Queries the database for total un-enriched cards across all sets."""
    engine = get_engine()
    
    # We use Postgres FILTER logic because it is significantly faster than standard CASE WHEN for large tables
    query = text("""
        SELECT 
            COUNT(*) FILTER (WHERE image_embedding IS NULL AND image_url IS NOT NULL) as missing_embeddings,
            COUNT(*) FILTER (WHERE supertype = 'Pokemon' AND (art_style IS NULL OR art_style = '"Manual review needed"')) as missing_styles
        FROM tcg_cards;
    """)
    
    try:
        with engine.connect() as conn:
            result = conn.execute(query).fetchone()
            return {
                "embeddings": result.missing_embeddings or 0,
                "styles": result.missing_styles or 0
            }
    except Exception as e:
        logger.error(f"Failed to fetch bulk counts: {e}")
        return {"embeddings": 0, "styles": 0}

# Load dropdown options safely
set_options = get_set_dropdown_options()

col1, col2 = st.columns(2, gap="large")

# --- COLUMN 1: TARGETED SET INGESTION ---
with col1:
    st.header("🎯 Targeted Set Ingestion")
    st.markdown("Fetch, embed, and enrich a specific set.")
    
    with st.form("targeted_ingest_form"):
        # The Dropdown UI
        selected_set_dict = None
        if set_options:
            selected_set_dict = st.selectbox(
                "Select a Set to Process:",
                options=set_options,
                format_func=lambda x: x["label"]
            )
        else:
            st.warning("⚠️ API disconnected and Database is empty. Proceeding with manual entry.")
            
        # The Manual Override (from your earlier code!)
        manual_set_id = st.text_input("Or enter Set ID manually (Overrides dropdown):", placeholder="e.g., swsh1, sv2")
            
        submit_targeted = st.form_submit_button("🚀 Run Targeted Pipeline", type="primary", use_container_width=True)
        
    if submit_targeted:
        # If manual is typed, use that. Otherwise, use the dropdown selection.
        target_set = manual_set_id.strip() if manual_set_id.strip() else (selected_set_dict["id"] if selected_set_dict else None)
        
        if not target_set:
            st.error("Please select or enter a valid Set ID.")
        else:
            logger.info(f"--- UI TRIGGER: Starting Targeted Pipeline for set '{target_set.upper()}' ---")
            
            with st.status(f"Executing Pipeline for Set: {target_set.upper()}", expanded=True) as status:
                progress_bar = st.progress(0)
                try:
                    st.write("📥 1/5: Fetching metadata from Pokémon TCG API...")
                    logger.info("Step 1: Initiating API fetch...")
                    progress_bar.progress(20)
                    
                    stats = run_end_to_end_pipeline(target_set=target_set)
                    
                    st.write(f"🧠 2/5: Calculating CLIP Embeddings ({stats['embedded']} cards)...")
                    logger.info(f"Step 2: CLIP Embeddings complete. Processed {stats['embedded']} cards.")
                    progress_bar.progress(40)
                    
                    st.write(f"👁️ 3/5: Running EasyOCR Corrections ({stats['ocr_fixed']} mislabels fixed)...")
                    logger.info(f"Step 3: OCR Audit complete. Fixed {stats['ocr_fixed']} cards.")
                    progress_bar.progress(60)
                    
                    st.write(f"🎨 4/5: Running KNN Art Style Enrichment ({stats['knn_enriched']} mapped)...")
                    logger.info(f"Step 4: KNN Enrichment complete. Mapped {stats['knn_enriched']} cards.")
                    progress_bar.progress(80)
                    
                    st.write("✨ 5/5: Aesthetics ML (Skipped - Awaiting Model Training)")
                    logger.info("Step 5: Aesthetics ML skipped.")
                    progress_bar.progress(100)
                    
                    status.update(label="✅ Targeted Pipeline Complete!", state="complete", expanded=False)
                    st.success(f"Successfully processed and enriched {stats['total']} cards from {target_set.upper()}!")
                    logger.info(f"--- SUCCESS: Pipeline finished for '{target_set.upper()}'. Total cards: {stats['total']} ---")
                    
                    # Clear cache and reset page
                    get_set_dropdown_options.clear()
                    time.sleep(2)
                    st.rerun()
                    
                except Exception as e:
                    status.update(label="❌ Pipeline Failed", state="error", expanded=True)
                    st.error(f"Error: {str(e)}")
                    logger.error(f"--- FAILURE: Pipeline crashed for '{target_set.upper()}'! Error: {str(e)} ---", exc_info=True)

# --- COLUMN 2: BULK CATCH-UP (UNPROCESSED DATA) ---
with col2:
    st.header("🏭 Bulk Catch-Up & Enrichment")
    st.markdown("Sweep the database for missing embeddings, un-audited labels, or unenriched art styles.")
    
    # Fetch live counts from the database!
    pending = get_pending_bulk_counts()
    
    with st.container(border=True):
        st.markdown("**Live Pending Queue:**")
        
        # Display the actual live database counts, formatted with commas for readability
        st.caption(f"• **{pending['embeddings']:,}** cards missing CLIP embeddings")
        st.caption(f"• **{pending['styles']:,}** cards requiring Art Style KNN enrichment")
        
        st.write("") 
        
        # Disable the button if there is absolutely nothing to do!
        is_disabled = (pending['embeddings'] == 0 and pending['styles'] == 0)
        
        if st.button("🔥 Run Bulk Catch-Up Pipeline", type="primary", use_container_width=True, disabled=is_disabled):
            logger.info("--- UI TRIGGER: Starting Bulk Catch-Up Pipeline ---")
            
            with st.status("Executing Bulk Catch-Up...", expanded=True) as status:
                progress_bar = st.progress(0)
                try:
                    st.write("📥 1/4: Checking for missing API data...")
                    logger.info("Step 1: Initiating bulk API check for missing cards...")
                    progress_bar.progress(25)
                    
                    # Run the backend
                    stats = run_end_to_end_pipeline(target_set=None)
                    
                    st.write(f"🧠 2/4: Calculating missing CLIP Embeddings ({stats['embedded']} processed)...")
                    progress_bar.progress(50)
                    
                    st.write(f"🎨 3/4: Running bulk KNN Art Style Enrichment ({stats['knn_enriched']} mapped)...")
                    progress_bar.progress(75)
                    
                    st.write("✨ 4/4: Aesthetics ML (Skipped - Awaiting Model Training)")
                    progress_bar.progress(100)
                    
                    status.update(label="✅ Bulk Catch-Up Complete!", state="complete", expanded=False)
                    st.success("Database is completely synchronized and enriched!")
                    
                    # CLEAR BOTH CACHES so the dropdowns AND the bulk numbers update instantly
                    get_set_dropdown_options.clear()
                    get_pending_bulk_counts.clear()
                    time.sleep(1.5)
                    st.rerun()
                    
                except Exception as e:
                    status.update(label="❌ Bulk Pipeline Failed", state="error", expanded=True)
                    st.error(f"Error: {str(e)}")
                    logger.error(f"--- FAILURE: Bulk Pipeline crashed! Error: {str(e)} ---", exc_info=True)