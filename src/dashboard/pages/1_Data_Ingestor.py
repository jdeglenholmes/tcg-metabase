import sys
import os
import streamlit as st
import pandas as pd
from sqlalchemy import text

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from src.dashboard.utils import render_sidebar, get_engine

st.set_page_config(page_title="Pipeline Monitor", layout="wide", page_icon="📥")
render_sidebar()

st.title("📥 Pipeline Monitor")
st.markdown("Cloud-safe observation deck. Track the health of your Supabase database and identify which local ingestion scripts need to be executed.")
st.divider()

engine = get_engine()

@st.cache_data(ttl=30)
def fetch_pipeline_health():
    """Scans the database to find missing data across the pipeline stages."""
    query = text("""
        SELECT 
            COUNT(*) as total_cards,
            COUNT(*) FILTER (WHERE image_url IS NULL) as missing_images,
            COUNT(*) FILTER (WHERE image_embedding IS NULL) as missing_embeddings,
            COUNT(*) FILTER (WHERE art_style IS NULL) as pending_classification
        FROM tcg_cards
        WHERE REPLACE(supertype, 'é', 'e') = 'Pokemon';
    """)
    with engine.connect() as conn:
        result = conn.execute(query).mappings().fetchone()
        return dict(result)

health = fetch_pipeline_health()

# --- HIGH-LEVEL METRICS ---
col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Pokémon Cards", f"{health['total_cards']:,}")
col2.metric("Pending Embeddings", f"{health['missing_embeddings']:,}", delta_color="inverse")
col3.metric("Pending Auto-Classification", f"{health['pending_classification']:,}", delta_color="inverse")
col4.metric("Missing Images", f"{health['missing_images']:,}", delta_color="inverse")

st.write("")
st.write("")

# --- ACTIONABLE PIPELINE STAGES ---
st.subheader("🛠️ Required Local Actions")
st.markdown("Run these commands in your local machine's terminal to process the backlog.")

# 1. API Ingestion
with st.container(border=True):
    st.markdown("### 1. API Ingestion (Fetch New Sets)")
    st.caption("Pulls raw data from the Pokémon TCG API into Supabase.")
    st.code("python src/scripts/run.py --set [SET_ID]", language="bash")

# 2. CLIP Embeddings
with st.container(border=True):
    st.markdown("### 2. Vector Generation (CLIP)")
    if health['missing_embeddings'] > 0:
        st.warning(f"**Action Required:** {health['missing_embeddings']:,} cards need image vectors generated for the Tinder Discovery UI.")
        st.code("python src/scripts/enrichment.py", language="bash")
    else:
        st.success("All cards have vector embeddings. No action needed.")

# 3. Auto-Classification
with st.container(border=True):
    st.markdown("### 3. Tier 3 Auto-Classification")
    if health['pending_classification'] > 0:
        st.info(f"**Action Required:** {health['pending_classification']:,} cards are waiting for zero-touch style assignment.")
        st.code("python src/scripts/auto_classify.py", language="bash")
    else:
        st.success("No cards pending auto-classification.")