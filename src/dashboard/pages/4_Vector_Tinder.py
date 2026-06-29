import sys
import os
import json
import streamlit as st
from sqlalchemy import text

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from src.dashboard.utils import render_sidebar, get_engine, SUGGESTED_REMAINING_STYLES

st.set_page_config(page_title="Vector Tinder", layout="wide", page_icon="🎯")
render_sidebar()

st.title("🎯 Vector Tinder Discovery")
st.markdown("Surface candidates for niche styles using similarity search.")

engine = get_engine()

# --- 1. SELECTION ---
selected_style = st.selectbox("Search for style candidates:", SUGGESTED_REMAINING_STYLES)

if st.button("Query Database for Matches"):
    # Finds cards closest to the FIRST card already labeled with this style
    # The <-> operator performs L2 distance search (perfect for CLIP vectors)
    query = text("""
        SELECT card_id, name, image_url, art_style 
        FROM tcg_cards 
        WHERE image_embedding IS NOT NULL
        ORDER BY image_embedding <-> (
            SELECT image_embedding 
            FROM tcg_cards 
            WHERE art_style @> :style_json 
            LIMIT 1
        )
        LIMIT 24;
    """)
    
    with engine.connect() as conn:
        results = conn.execute(query, {"style_json": json.dumps([selected_style])}).mappings().fetchall()
        
    if not results:
        st.warning("No existing labeled examples found to seed the search. Label one card with this style first!")
    else:
        # --- 2. GRID DISPLAY ---
        cols = st.columns(4)
        for i, row in enumerate(results):
            with cols[i % 4]:
                st.image(row['image_url'], use_container_width=True)
                st.caption(f"**{row['name']}**")
                
                # Inline approve/reject
                if st.button(f"✅ Confirm {selected_style}", key=f"app_{row['card_id']}"):
                    with engine.begin() as conn:
                        conn.execute(text("UPDATE tcg_cards SET art_style = :s, labeled_by = 'Human_Audit' WHERE card_id = :id"),
                                     {"s": json.dumps([selected_style]), "id": row['card_id']})
                    st.rerun()
                
                if st.button(f"❌ Reject", key=f"rej_{row['card_id']}"):
                    with engine.begin() as conn:
                        conn.execute(text("UPDATE tcg_cards SET art_style = '\"Manual review needed\"', labeled_by = 'Human_Audit' WHERE card_id = :id"),
                                     {"id": row['card_id']})
                    st.rerun()