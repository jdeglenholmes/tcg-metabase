import sys
import os
# Go up 3 levels from src/dashboard/pages/ to the repository root
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)
    
import streamlit as st
import json
from sqlalchemy import text
from src.dashboard.utils import render_sidebar, get_engine, ART_STYLE_KEYS

st.set_page_config(page_title="Central Auditor", layout="wide")
render_sidebar()

st.title("⚖️ Central Auditor (Active Learning)")
st.markdown("Override incorrect labels to create high-gravity 'Human Anchors' for the ML pipeline.")

engine = get_engine()

# --- 1. FILTER CONTROLS ---
col1, col2 = st.columns(2)
with col1:
    view_mode = st.radio("View Mode:", ["Unlabeled / Needs Review", "Currently Labeled"])
with col2:
    selected_style = None
    if view_mode == "Currently Labeled":
        selected_style = st.selectbox("Filter by specific style to audit:", options=["ALL"] + ART_STYLE_KEYS)

# --- 2. BUILD THE QUERY ---
query_str = """
    SELECT card_id, name, illustrator, image_url, art_style, labeled_by 
    FROM tcg_cards 
    WHERE REPLACE(supertype, 'é', 'e') = 'Pokemon' AND image_url IS NOT NULL
"""

if view_mode == "Unlabeled / Needs Review":
    # LINE 31 FIXED: Clean SQL termination
    query_str += " AND (art_style IS NULL OR art_style = '\"Manual review needed\"')"
else:
    if selected_style and selected_style != "ALL":
        query_str += f" AND art_style = '\"{selected_style}\"'"
    else:
        query_str += " AND art_style IS NOT NULL AND art_style != '\"Manual review needed\"'"

query_str += " ORDER BY RANDOM() LIMIT 20" 

# Fetch Data
with engine.connect() as conn:
    cards = conn.execute(text(query_str)).mappings().fetchall()

# --- 3. THE INTERACTIVE FRAGMENT ---
@st.fragment
def render_card_override(card):
    # Robust parsing to handle both JSON-quoted strings and raw strings
    current_val = None
    if card['art_style']:
        try:
            current_val = json.loads(card['art_style'])
        except (json.JSONDecodeError, TypeError):
            current_val = card['art_style'] # Fallback if it's already a plain string
            
    idx = ART_STYLE_KEYS.index(current_val) if current_val in ART_STYLE_KEYS else 0
    
    st.image(card['image_url'], use_container_width=True)
    st.caption(f"** | {card['illustrator']}")
    
    if card['labeled_by']:
         st.markdown(f"*{card['labeled_by']}*")
    
    new_style = st.selectbox(
        "Assign Style:", 
        options=ART_STYLE_KEYS, 
        index=idx, 
        key=f"select_{card['card_id']}",
        label_visibility="collapsed"
    )
    
    if st.button("Lock Anchor", key=f"btn_{card['card_id']}", use_container_width=True):
        with engine.begin() as conn:
            conn.execute(text("""
                UPDATE tcg_cards 
                SET art_style = :style, labeled_by = 'Human_Audit'
                WHERE card_id = :id
            """), {
                "style": json.dumps(new_style), 
                "id": card['card_id']
            })
        st.success("Anchor Locked!")
        
# --- 4. RENDER THE GRID ---
st.divider()
if not cards:
    st.info("No cards found for this filter combination.")
else:
    cols = st.columns(4)
    for i, card in enumerate(cards):
        with cols[i % 4]:
            with st.container(border=True):
                 render_card_override(card)
                 
    if st.button("🔄 Fetch Next Batch of 20", type="primary"):
        st.rerun()