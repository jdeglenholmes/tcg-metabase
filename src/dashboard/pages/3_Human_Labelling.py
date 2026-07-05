import sys
import os
import json
import requests
from io import BytesIO
from PIL import Image
import streamlit as st
from sqlalchemy import text
from pydantic import BaseModel, Field
from google import genai

# Setup paths
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from src.dashboard.utils import render_sidebar, get_engine, ART_STYLE_KEYS

class AppraisalResult(BaseModel):
    style: str = Field(description="The exact name of the selected art style category.")
    reason: str = Field(description="A brief, 1-sentence justification.")

st.set_page_config(page_title="Central Auditor", layout="wide")
render_sidebar()

st.title("⚖️ Central Auditor (Active Learning)")
st.markdown("Lock in human anchors or use Gemini AI for a second opinion.")

engine = get_engine()

# --- OPTIMIZED HELPERS ---
def parse_art_style(raw_style):
    if not raw_style: return ART_STYLE_KEYS[0]
    try:
        parsed = json.loads(raw_style)
        return parsed[0] if isinstance(parsed, list) else parsed
    except: return raw_style

# --- CALLBACK: PERSISTENT SAVE ---
def update_card_callback(card_id):
    new_style = st.session_state[f"select_{card_id}"]
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE tcg_cards 
            SET art_style = :style, labeled_by = 'Human_Audit', updated_at = CURRENT_TIMESTAMP
            WHERE card_id = :id
        """), {"style": json.dumps([new_style]), "id": card_id})
    fetch_cards.clear() # Clear cache so UI refreshes immediately
    st.toast(f"Saved: {new_style}")

# --- DATA FETCHING (CACHED) ---
@st.cache_data(ttl=60, show_spinner=False)
def fetch_cards(mode, style, search, limit):
    base_query = """SELECT card_id, name, illustrator, rarity, market_price, image_url, art_style FROM tcg_cards WHERE REPLACE(supertype, 'é', 'e') = 'Pokemon' AND image_url IS NOT NULL"""
    params, count_params = {}, {}
    
    if mode == "Unlabeled / Needs Review":
        cond = " AND (art_style IS NULL OR art_style::text IN ('\"Manual review needed\"', '[\"Manual review needed\"]'))"
        base_query += cond
    elif mode == "Currently Labeled" and style and style != "ALL":
        base_query += " AND art_style @> :style"
        params["style"] = json.dumps([style])
    elif mode == "Find Specific Card" and search:
        base_query += " AND (name ILIKE :s OR card_id ILIKE :s)"
        params["s"] = f"%{search}%"
        
    base_query += " ORDER BY RANDOM() LIMIT :limit"
    params["limit"] = limit
    
    with engine.connect() as conn:
        return [dict(c) for c in conn.execute(text(base_query), params).mappings().fetchall()]

# --- UI CONTROLS ---
col1, col2, col3 = st.columns([2, 2, 1])
with col1:
    view_mode = st.radio("View Mode:", ["Unlabeled / Needs Review", "Currently Labeled", "Find Specific Card"])
with col2:
    style_filter = st.selectbox("Style:", ["ALL"] + ART_STYLE_KEYS) if view_mode == "Currently Labeled" else None
    search_input = st.text_input("Search:") if view_mode == "Find Specific Card" else None
with col3:
    display_limit = st.number_input("Limit:", 4, 100, 24, 4)

cards = fetch_cards(view_mode, style_filter, search_input, display_limit)

# --- RENDER GRID ---
st.divider()
if not cards:
    st.info("No cards found.")
else:
    cols = st.columns(4)
    for i, card in enumerate(cards):
        with cols[i % 4]:
            with st.container(border=True):
                st.image(card['image_url'], use_container_width=True)
                
                with st.expander(f"📖 {card['name']}"):
                    st.markdown(f"**Artist:** {card.get('illustrator') or '⚠️'}")
                    st.markdown(f"**Rarity:** {card.get('rarity') or '⚠️'}")
                    st.markdown(f"**Price:** ${card.get('market_price') or 0:.2f}")

                current_val = parse_art_style(card['art_style'])
                
                st.selectbox(
                    "Assign Style:", 
                    options=ART_STYLE_KEYS, 
                    index=ART_STYLE_KEYS.index(current_val) if current_val in ART_STYLE_KEYS else 0,
                    key=f"select_{card['card_id']}",
                    on_change=update_card_callback,
                    args=(card['card_id'],),
                    label_visibility="collapsed"
                )
                
                # Gemini Advisor (Non-persistent, purely informational)
                if st.button("🤖 Ask Gemini", key=f"gemini_{card['card_id']}", use_container_width=True):
                    with st.spinner("Analyzing..."):
                        try:
                            client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
                            img = Image.open(BytesIO(requests.get(card['image_url']).content))
                            resp = client.models.generate_content(
                                model='gemini-2.5-flash',
                                contents=[f"Classify this into one of: {ART_STYLE_KEYS}", img],
                                config={"response_mime_type": "application/json", "response_schema": AppraisalResult}
                            )
                            ai = AppraisalResult.model_validate_json(resp.text)
                            st.success(f"**{ai.style}**")
                            st.caption(ai.reason)
                        except Exception as e:
                            st.error(f"API Error: {e}")