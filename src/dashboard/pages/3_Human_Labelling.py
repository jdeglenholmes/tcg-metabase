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
        # Only allow auditing of your high-confidence core styles
        selected_style = st.selectbox("Filter by specific style to audit:", options=["ALL"] + CORE_STYLES)

# --- 2. BUILD THE QUERY ---
query_str = """
    SELECT card_id, name, illustrator, image_url, art_style, labeled_by 
    FROM tcg_cards 
    WHERE REPLACE(supertype, 'é', 'e') = 'Pokemon' AND image_url IS NOT NULL
"""

params = {}

if view_mode == "Unlabeled / Needs Review":
    query_str += " AND (art_style IS NULL OR art_style = :review_label)"
    params["review_label"] = json.dumps("Manual review needed")
else:
    if selected_style and selected_style != "ALL":
        query_str += " AND art_style = :style"
        params["style"] = json.dumps(selected_style)
    else:
        style_placeholders = [f":style_{i}" for i in range(len(CORE_STYLES))]
        query_str += f" AND art_style IN ({', '.join(style_placeholders)})"
        for i, style in enumerate(CORE_STYLES):
            params[f"style_{i}"] = json.dumps(style)

query_str += " LIMIT 24;"

with engine.connect() as conn:
    result = conn.execute(text(query_str), params).mappings().fetchall()
    cards = [dict(row) for row in result]

# --- 3. RENDER THE GRID ---
st.divider()
if not cards:
    st.info("No cards found matching this criteria.")
else:
    cols = st.columns(4)
    for i, card in enumerate(cards):
        with cols[i % 4]:
            with st.container(border=True):
                st.image(card['image_url'], use_container_width=True)
                st.caption(f"** | {card['illustrator'] if card['illustrator'] else 'Unknown'}")
                
                if card['labeled_by']:
                    st.caption(f"*Logged by: {card['labeled_by']}*")
                
                # Unpack array or string stored in database JSON column
                current_val = card['art_style']
                if isinstance(current_val, str):
                    try:
                        loaded = json.loads(current_val)
                        if isinstance(loaded, list) and len(loaded) > 0:
                            current_val = loaded[0]
                        elif isinstance(loaded, str):
                            current_val = loaded
                    except (json.JSONDecodeError, TypeError):
                        pass
                        
                idx = CORE_STYLES.index(current_val) if current_val in CORE_STYLES else 0
                
                new_style = st.selectbox(
                    "Assign Style:", 
                    options=CORE_STYLES, 
                    index=idx, 
                    key=f"select_{card['card_id']}_{i}",
                    label_visibility="collapsed"
                )
                
                if st.button("Lock Anchor", key=f"btn_{card['card_id']}_{i}", type="primary", use_container_width=True):
                    # Save back to database wrapped as an array to match project spec
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