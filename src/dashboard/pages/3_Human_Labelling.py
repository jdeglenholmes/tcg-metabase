import sys
import os
import json
from sqlalchemy import text
import streamlit as st

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from src.dashboard.utils import render_sidebar, get_engine, CORE_STYLES

st.set_page_config(page_title="Central Auditor", layout="wide")
render_sidebar()

st.title("⚖️ Central Auditor (Core Ground Truth)")
st.markdown("Lock in clean human anchors for the high-confidence, easily identifiable core art styles.")

engine = get_engine()

# --- 1. FILTER CONTROLS ---
col1, col2 = st.columns(2)
with col1:
    view_mode = st.radio("View Mode:", ["Unlabeled / Needs Review", "Currently Labeled"])
with col2:
    selected_style = None
    if view_mode == "Currently Labeled":
        selected_style = st.selectbox("Filter by specific style to audit:", options=["ALL"] + CORE_STYLES)

# --- 2. BUILD THE QUERY ---
query_str = """
    SELECT card_id, name, illustrator, image_url, art_style, labeled_by 
    FROM tcg_cards 
    WHERE REPLACE(supertype, 'é', 'e') = 'Pokemon'
"""
params = {}

if view_mode == "Unlabeled / Needs Review":
    # Safely target NULLs and both versions of the manual review flag
    query_str += " AND (art_style IS NULL OR art_style::text = '\"Manual review needed\"' OR art_style::text = '[\"Manual review needed\"]')"
else:
    if selected_style != "ALL":
        # Use pgvector JSON containment operator
        query_str += " AND art_style @> :style_json"
        params['style_json'] = json.dumps([selected_style])
    else:
        query_str += " AND art_style IS NOT NULL AND art_style::text != '\"Manual review needed\"' AND art_style::text != '[\"Manual review needed\"]'"
        
query_str += " ORDER BY RANDOM() LIMIT 24"

with engine.connect() as conn:
    cards = conn.execute(text(query_str), params).mappings().fetchall()

# --- 3. DISPLAY GRID ---
if not cards:
    st.success("No cards found matching this filter! Great job.")
else:
    cols = st.columns(4)
    for i, card in enumerate(cards):
        with cols[i % 4]:
            st.image(card['image_url'], use_container_width=True)
            st.caption(f"**{card['name']}**")
            
            # --- ROBUST JSON PARSER ---
            current_val = CORE_STYLES[0] # Fallback
            raw_style = card.get('art_style')
            
            if raw_style:
                if isinstance(raw_style, list) and len(raw_style) > 0:
                    current_val = raw_style[0]
                elif isinstance(raw_style, str):
                    try:
                        parsed = json.loads(raw_style)
                        if isinstance(parsed, list) and len(parsed) > 0:
                            current_val = parsed[0]
                        elif isinstance(parsed, str):
                            current_val = parsed
                    except Exception:
                        current_val = raw_style
                        
            # Find index safely, default to 0 if style is entirely new
            idx = CORE_STYLES.index(current_val) if current_val in CORE_STYLES else 0
            
            new_style = st.selectbox(
                "Assign Style:", 
                options=CORE_STYLES, 
                index=idx, 
                key=f"select_{card['card_id']}_{i}",
                label_visibility="collapsed"
            )
            
            if st.button("Lock Anchor", key=f"btn_{card['card_id']}_{i}", type="primary", use_container_width=True):
                with engine.begin() as conn:
                    conn.execute(text("""
                        UPDATE tcg_cards 
                        SET art_style = :style, labeled_by = 'Human_Audit', updated_at = CURRENT_TIMESTAMP
                        WHERE card_id = :id
                    """), {
                        "style": json.dumps([new_style]), 
                        "id": card['card_id']
                    })
                st.toast(f"Locked {card['name']} as {new_style}!")
                st.rerun()