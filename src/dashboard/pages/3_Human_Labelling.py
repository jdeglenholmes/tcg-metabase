import sys
import os
import requests
from io import BytesIO
from PIL import Image

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

import streamlit as st
import json
from sqlalchemy import text
from pydantic import BaseModel, Field
from google import genai
from src.dashboard.utils import render_sidebar, get_engine, ART_STYLE_KEYS

class AppraisalResult(BaseModel):
    style: str = Field(description="The exact name of the selected art style category.")
    reason: str = Field(description="A brief, 1-sentence justification explaining the medium or aesthetic.")

st.set_page_config(page_title="Human Labelling", layout="wide")
render_sidebar()

st.title("⚖️ Central Auditor (Active Learning)")
st.markdown("Lock in human anchors, or ask the Gemini model for a second opinion directly from the card view.")

engine = get_engine()

# --- 1. UI CONTROLS ---
col1, col2, col3 = st.columns([2, 2, 1])
with col1:
    view_mode = st.radio("View Mode:", ["Unlabeled / Needs Review", "Currently Labeled", "Find Specific Card"])
with col2:
    selected_style = None
    search_query = None
    if view_mode == "Currently Labeled":
        selected_style = st.selectbox("Filter by specific style:", options=["ALL"] + ART_STYLE_KEYS)
    elif view_mode == "Find Specific Card":
        search_query = st.text_input("Enter Card Name or ID:")
with col3:
    display_limit = st.number_input("Max Cards to Display:", min_value=4, max_value=200, value=24, step=4)

# --- 2. DATA FETCHING (CACHED TO PREVENT LAG) ---
@st.cache_data(ttl=60, show_spinner=False)
def fetch_cards(mode, style, search, limit):
    base_query = """
        SELECT card_id, name, illustrator, rarity, market_price, image_url, art_style, labeled_by 
        FROM tcg_cards 
        WHERE REPLACE(supertype, 'é', 'e') = 'Pokemon' AND image_url IS NOT NULL
    """
    # Use separate param dictionaries to keep SQLAlchemy perfectly clean
    params = {}
    count_params = {}
    
    count_query = "SELECT COUNT(*) FROM tcg_cards WHERE REPLACE(supertype, 'é', 'e') = 'Pokemon' AND image_url IS NOT NULL"
    
    if mode == "Unlabeled / Needs Review":
        condition = " AND (art_style IS NULL OR art_style = '\"Manual review needed\"')"
        base_query += condition
        count_query += condition
    elif mode == "Currently Labeled":
        if style and style != "ALL":
            condition = " AND art_style = :style"
            base_query += condition
            count_query += condition
            params["style"] = f'"{style}"'
            count_params["style"] = f'"{style}"'
        else:
            condition = " AND art_style != '\"Manual review needed\"' AND art_style IS NOT NULL"
            base_query += condition
            count_query += condition
    elif mode == "Find Specific Card":
        if search:
            condition = " AND (name ILIKE :search OR card_id ILIKE :search)"
            base_query += condition
            count_query += condition
            params["search"] = f"%{search}%"
            count_params["search"] = f"%{search}%"
        else:
            return [], 0
            
    base_query += " LIMIT :limit;"
    params["limit"] = limit
    
    with engine.connect() as conn:
        total_count = conn.execute(text(count_query), count_params).scalar()
        fetched_cards = conn.execute(text(base_query), params).mappings().fetchall()
        return [dict(c) for c in fetched_cards], total_count

cards, total_match_count = fetch_cards(view_mode, selected_style, search_query, display_limit)

# --- 3. METRICS DISPLAY ---
if view_mode != "Find Specific Card":
    st.info(f"**Total matching cards in database:** {total_match_count:,} (Showing top {len(cards)})")

# --- 4. RENDER THE GRID ---
st.divider()
if not cards:
    if view_mode == "Find Specific Card" and not search_query:
        st.info("Enter a name or ID above to search.")
    else:
        st.info("No cards found matching this criteria.")
else:
    cols = st.columns(4)
    for i, card in enumerate(cards):
        with cols[i % 4]:
            with st.container(border=True):
                st.image(card['image_url'], use_container_width=True)
                
                with st.expander(f"📖 {card['name']} Details"):
                    st.markdown(f"Illustrator: " if card['illustrator'] else "⚠️ Missing")
                    st.markdown(f"Rarity: " if card['rarity'] else "⚠️ Missing")
                    price_display = f"${card['market_price']:.2f}" if card['market_price'] else "⚠️ Missing"
                    st.markdown(f"**Market Price:** {price_display}")
                
                # Load existing labels
                current_val = card['art_style']
                if isinstance(current_val, str) and current_val.startswith('"'):
                    try:
                        current_val = json.loads(current_val)
                    except:
                        pass
                idx = ART_STYLE_KEYS.index(current_val) if current_val in ART_STYLE_KEYS else 0
                
                new_style = st.selectbox(
                    "Assign Style:", 
                    options=ART_STYLE_KEYS, 
                    index=idx, 
                    key=f"select_{card['card_id']}",
                    label_visibility="collapsed"
                )
                
                # Inline Gemini AI Call
                if st.button("🤖 Ask Gemini", key=f"gemini_{card['card_id']}", use_container_width=True):
                    with st.spinner("Analyzing artwork..."):
                        try:
                            client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
                            img_response = requests.get(card['image_url'])
                            img = Image.open(BytesIO(img_response.content))
                            
                            prompt = f"Classify this Pokemon card art into exactly ONE of these categories: {ART_STYLE_KEYS}"
                            response = client.models.generate_content(
                                model='gemini-2.5-flash',
                                contents=[prompt, img],
                                config={
                                    "temperature": 0.0,
                                    "response_mime_type": "application/json",
                                    "response_schema": AppraisalResult,
                                }
                            )
                            ai_decision = AppraisalResult.model_validate_json(response.text)
                            if ai_decision.style in ART_STYLE_KEYS:
                                st.success(f"**{ai_decision.style}**")
                                st.caption(ai_decision.reason)
                            else:
                                st.error(f"Invalid style chosen: {ai_decision.style}")
                        except Exception as e:
                            st.error(f"API Error: {e}")
                
                # Save Label and clear cache to update UI seamlessly
                if st.button("Lock Anchor", key=f"btn_{card['card_id']}", type="primary", use_container_width=True):
                    with engine.begin() as conn:
                        conn.execute(text("""
                            UPDATE tcg_cards 
                            SET art_style = :style, labeled_by = 'Human_Audit', updated_at = CURRENT_TIMESTAMP
                            WHERE card_id = :id
                        """), {
                            "style": json.dumps(new_style), 
                            "id": card['card_id']
                        })
                    fetch_cards.clear()
                    st.rerun()