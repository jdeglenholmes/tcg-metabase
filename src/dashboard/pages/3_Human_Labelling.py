import sys
import os
import json
from sqlalchemy import text
import streamlit as st

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from src.dashboard.utils import render_sidebar, get_engine, ART_STYLE_KEYS

st.set_page_config(page_title="Central Auditor", layout="wide")
render_sidebar()

st.title("⚖️ Central Auditor (Core Ground Truth)")
st.markdown("Lock in clean human anchors for the high-confidence, easily identifiable core art styles.")

engine = get_engine()

# --- OPTIMIZED HELPER FUNCTIONS ---
# Defined once, outside the loop, to improve Streamlit rendering performance
def safe_display(val):
    if not val or str(val).strip() in ["", "Unknown", "None"]:
        return "⚠️ Missing"
    return str(val)

def parse_art_style(raw_style, fallback_style):
    if not raw_style:
        return fallback_style
    if isinstance(raw_style, list) and len(raw_style) > 0:
        return raw_style[0]
    if isinstance(raw_style, str):
        try:
            parsed = json.loads(raw_style)
            if isinstance(parsed, list) and len(parsed) > 0:
                return parsed[0]
            if isinstance(parsed, str):
                return parsed
        except Exception:
            return raw_style
    return fallback_style

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
    SELECT card_id, name, illustrator, rarity, market_price, image_url, art_style, labeled_by 
    FROM tcg_cards 
    WHERE REPLACE(supertype, 'é', 'e') = 'Pokemon'
"""
params = {}

if view_mode == "Unlabeled / Needs Review":
    query_str += " AND (art_style IS NULL OR art_style::text = '\"Manual review needed\"' OR art_style::text = '[\"Manual review needed\"]')"
else:
    if selected_style != "ALL":
        query_str += " AND art_style @> :style_json"
        params['style_json'] = json.dumps([selected_style])
    else:
        query_str += " AND art_style IS NOT NULL AND art_style::text != '\"Manual review needed\"' AND art_style::text != '[\"Manual review needed\"]'"
        
query_str += " ORDER BY RANDOM() LIMIT 24"

with engine.connect() as conn:
    cards = conn.execute(text(query_str), params).mappings().fetchall()

st.divider()

# --- 3. DISPLAY GRID ---
if not cards:
    st.success("🎉 No cards found matching this filter! Your baseline is secure.")
else:
    st.info(f"Displaying up to 24 cards requiring your review.")
    cols = st.columns(4)
    for i, card in enumerate(cards):
        with cols[i % 4]:
            # Standardized visual framing
            with st.container(border=True):
                st.image(card['image_url'], use_container_width=True)
                
                # Standardized Expandable Metadata
                with st.expander(f"📖 {card['name']} Details"):
                    st.markdown(f"**Illustrator:** {safe_display(card.get('illustrator'))}")
                    st.markdown(f"**Rarity:** {safe_display(card.get('rarity'))}")
                    
                    price = card.get('market_price')
                    price_display = f"${price:.2f}" if price else "⚠️ Missing"
                    st.markdown(f"**Market Price:** {price_display}")
                
                # Fetch and format the correct starting index for the dropdown
                current_val = parse_art_style(card.get('art_style'), ART_STYLE_KEYS[0])
                idx = ART_STYLE_KEYS.index(current_val) if current_val in ART_STYLE_KEYS else 0
                
                new_style = st.selectbox(
                    "Assign Style:", 
                    options=ART_STYLE_KEYS, 
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