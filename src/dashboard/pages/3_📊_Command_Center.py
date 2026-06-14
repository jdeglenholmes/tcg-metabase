# src/dashboard/pages/3_📊_Command_Center.py
import streamlit as st
import pandas as pd
from sqlalchemy import text
from src.dashboard.utils import get_engine, render_sidebar

st.set_page_config(page_title="...", layout="wide")
render_sidebar()

st.title("📊 Pipeline Command Center")
st.markdown("Intelligent metrics, database health tracking, and automated directives.")

engine = get_engine()

# --- 1. GATHER METRICS (Lightning fast SQL Aggregation) ---
with engine.connect() as conn:
    # Volume Metrics
    vol_query = text("SELECT COUNT(*) as total, COUNT(DISTINCT set_id) as sets FROM tcg_cards")
    vol_res = conn.execute(vol_query).fetchone()
    total_cards, total_sets = vol_res[0], vol_res[1]
    
    # DB Health Metrics
    health_query = text("""
        SELECT 
            SUM(CASE WHEN image_url IS NULL THEN 1 ELSE 0 END) as missing_images,
            SUM(CASE WHEN image_embedding IS NULL AND image_url IS NOT NULL THEN 1 ELSE 0 END) as missing_embeddings
        FROM tcg_cards
    """)
    health_res = conn.execute(health_query).fetchone()
    missing_images, missing_embeddings = health_res[0] or 0, health_res[1] or 0
    
    # Model/Tagging Health Metrics
    model_query = text("""
        SELECT 
            SUM(CASE WHEN art_style IS NOT NULL AND art_style != '"Manual review needed"' THEN 1 ELSE 0 END) as knn_assigned,
            SUM(CASE WHEN art_style = '"Manual review needed"' THEN 1 ELSE 0 END) as manual_review,
            SUM(CASE WHEN tags::text LIKE '%flagged_suspicious%' THEN 1 ELSE 0 END) as flagged
        FROM tcg_cards
        WHERE REPLACE(supertype, 'é', 'e') = 'Pokemon'
    """)
    model_res = conn.execute(model_query).fetchone()
    knn_assigned, manual_review, flagged = model_res[0] or 0, model_res[1] or 0, model_res[2] or 0

pokemon_count = knn_assigned + manual_review

# --- 2. INTELLIGENT MID-LAYER (Suggestion Engine) ---
st.header("🧠 Intelligent Directives")

suggestions = []
if total_cards == 0:
    suggestions.append("🔴 **CRITICAL:** Database is empty. Head to **Module 1 (Data Ingestor)** and fetch your first set.")
else:
    if missing_images > 0 or missing_embeddings > 0:
        suggestions.append(f"🟠 **DB HEALTH:** Found {missing_embeddings} cards missing CLIP embeddings. Run a Bulk Sweep in **Module 1**.")
    
    if manual_review > 0:
        suggestions.append(f"🟡 **MODEL HEALTH:** KNN was unsure about {manual_review} cards. Head to **Module 2 (Card Fetcher)**, filter by 'Manual review needed', and assign them to reach your 100% tag goal.")
        
    if flagged > 0:
        suggestions.append(f"🟣 **AI CRITIC QUEUE:** {flagged} cards are flagged as suspicious. Review these in **Module 2** to lower your disagreement tolerance.")
        
    if missing_embeddings == 0 and manual_review == 0 and flagged == 0:
        suggestions.append("🟢 **PIPELINE PERFECT:** Art styles are 100% mapped and synchronized! You are ready to move on to Aesthetic Model Training.")

# Render Suggestions
for sug in suggestions:
    st.info(sug)

st.divider()

# --- 3. DASHBOARD VISUALS ---
col1, col2, col3 = st.columns(3)

with col1:
    st.subheader("🗄️ Database Volume")
    st.metric("Total Cards Ingested", f"{total_cards:,}")
    st.metric("Total Sets Indexed", f"{total_sets:,}")
    st.metric("Valid Pokémon Cards", f"{pokemon_count:,}")

with col2:
    st.subheader("🏥 Database Health")
    st.metric("Missing Image URLs", f"{missing_images:,}", delta="Orphaned Data" if missing_images > 0 else "Perfect", delta_color="inverse")
    st.metric("Missing CLIP Vectors", f"{missing_embeddings:,}", delta="Needs Embedding" if missing_embeddings > 0 else "Fully Embedded", delta_color="inverse")

with col3:
    st.subheader("🤖 Model Health (Art Styles)")
    st.metric("KNN / Human Assigned", f"{knn_assigned:,}")
    st.metric("Ambiguous (Needs Review)", f"{manual_review:,}", delta="Pending human assignment" if manual_review > 0 else "Clear", delta_color="inverse")
    st.metric("Suspicious Flags", f"{flagged:,}", delta="Pending AI audit resolution" if flagged > 0 else "Clear", delta_color="inverse")