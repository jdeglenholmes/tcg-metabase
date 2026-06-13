# src/dashboard/pages/1_📥_Data_Ingestor.py
import streamlit as st
import sys
from src.dashboard.utils import (
    render_sidebar, get_engine, fetch_all_pokemon_sets, 
    text, run_pipeline_live
)

st.set_page_config(page_title="Data Ingestor", layout="wide", page_icon="📥")
user_name, selected_set = render_sidebar()
engine = get_engine()

st.title("📥 Data Ingestor")
st.write("Manage raw API data and generate visual embeddings for the Active Learning pipeline.")

# --- 1. DATASET HEALTH DASHBOARD ---
st.subheader("📊 Dataset Health")
with engine.connect() as conn:
    total_cards = conn.execute(text("SELECT COUNT(*) FROM tcg_cards")).scalar() or 0
    total_sets = conn.execute(text("SELECT COUNT(DISTINCT split_part(card_id, '-', 1)) FROM tcg_cards")).scalar() or 0
    total_embeddings = conn.execute(text("SELECT COUNT(*) FROM tcg_cards WHERE image_embedding IS NOT NULL")).scalar() or 0
    total_labeled = conn.execute(text("SELECT COUNT(*) FROM tcg_cards WHERE tags IS NOT NULL")).scalar() or 0
    
m1, m2, m3, m4 = st.columns(4)
m1.metric("Cards Ingested", f"{total_cards:,}")
m2.metric("Sets Tracked", f"{total_sets:,}")
pct_embedded = (total_embeddings / max(total_cards, 1)) * 100
m3.metric("Embeddings Generated", f"{total_embeddings:,}", f"{pct_embedded:.1f}% Coverage", delta_color="normal")
m4.metric("Human Verified Labels", f"{total_labeled:,}")
st.write("---")

all_sets = fetch_all_pokemon_sets()
db_status_query = text("""
    SELECT split_part(card_id, '-', 1) as set_prefix, COUNT(*) as total_cards, SUM(CASE WHEN image_embedding IS NOT NULL THEN 1 ELSE 0 END) as embedded_cards
    FROM tcg_cards GROUP BY set_prefix;
""")

with engine.connect() as conn:
    db_results = conn.execute(db_status_query).fetchall()
    
db_state = {row.set_prefix: {'total': row.total_cards, 'embedded': row.embedded_cards} for row in db_results}

set_options = {}
if all_sets:
    for s in all_sets:
        set_id, set_name = s['id'], s['name']
        state = db_state.get(set_id)
        if not state or state['total'] == 0: status_icon = "🔴" 
        elif state['embedded'] < state['total']: status_icon = "🟡" 
        else: status_icon = "🟢" 
        set_options[set_id] = f"{status_icon} {set_name} ({set_id})"

col_left, col_right = st.columns(2)
with col_left:
    st.subheader("🎯 Targeted Ingestion")
    st.info("Legend: 🔴 Not Ingested | 🟡 Missing Embeddings | 🟢 Ready for Labeler")
    selected_set_id = st.selectbox("Search and select a set:", options=list(set_options.keys()), format_func=lambda x: set_options.get(x, x))
    
    if st.button("📥 Ingest & Process Target Set", type="primary", use_container_width=True):
        success_ingest, _ = run_pipeline_live([sys.executable, "-m", "src.ingest.run", "--ingest", "--set_name", selected_set_id], f"Ingesting API Data: {set_options[selected_set_id]}")
        if success_ingest:
            success_enrich, _ = run_pipeline_live([sys.executable, "-m", "src.ingest.run", "--enrich", "--set_name", selected_set_id], f"Generating Visual Embeddings: {set_options[selected_set_id]}")
            if success_enrich:
                st.success(f"✨ {selected_set_id} fully processed and ready for the Data Labeler!")
            else:
                st.error("⚠️ Ingestion succeeded, but visual embedding generation failed.")
        else:
            st.error(f"❌ Ingestion completely failed for '{selected_set_id}'.")

with col_right:
    st.subheader("🌍 Bulk Operations")
    st.warning("These operations scan the entire database. They may take a significant amount of time depending on hardware limits.")
    if st.button("🧠 Process All Missing Embeddings", use_container_width=True):
        success, _ = run_pipeline_live([sys.executable, "-m", "src.ingest.run", "--enrich"], "Bulk Generating Missing Embeddings")
        if success: st.rerun()

    st.markdown("**Mass API Sync**")
    if st.button("⚠️ Ingest & Process ALL API Sets", use_container_width=True):
        st.error("This will attempt to ingest 15,000+ cards from the Pokémon API. Are you sure?")
        if st.button("🚨 Yes, Execute Mass Sync"):
            for s_id in set_options.keys():
                st.toast(f"Starting {s_id}...")
                run_pipeline_live([sys.executable, "-m", "src.ingest.run", "--ingest", "--set_name", s_id], f"Ingesting {s_id}")
                run_pipeline_live([sys.executable, "-m", "src.ingest.run", "--enrich", "--set_name", s_id], f"Embedding {s_id}")
            st.balloons()

# --- 2. DANGER ZONE (DATABASE MAINTENANCE) ---
st.markdown("---")
st.subheader("⚠️ Danger Zone")
with st.expander("Reset All Card Labels & Tags"):
    st.warning("This will permanently delete all human-verified and AI-bootstrapped tags, art styles, and aesthetics from the database. **Your 512-D CLIP embeddings will remain safe.**")
    
    confirm_reset = st.checkbox("I understand this action cannot be undone.")
    if confirm_reset and st.button("🗑️ Nuke All Tags", type="primary"):
        with engine.begin() as conn:
            conn.execute(text("""
                UPDATE tcg_cards 
                SET tags = NULL, 
                    art_style = NULL, 
                    card_aesthetic = NULL;
            """))
            # Optional: Clear the bootstrapper history so you don't get confused by old prompt logs
            conn.execute(text("TRUNCATE TABLE bootstrap_history;")) 
        st.success("✅ All tags have been completely wiped. You are ready to start fresh!")
        st.rerun()