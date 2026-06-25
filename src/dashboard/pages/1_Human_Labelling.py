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

# --- 1. FILTER CONTROLS ---
col1, col2 = st.columns(2)
with col1:
    view_mode = st.radio("View Mode:", ["Unlabeled / Needs Review", "Currently Labeled"])
with col2:
    selected_style = None
    if view_mode == "Currently Labeled":
        selected_style = st.selectbox("Filter by specific style to audit:", options=["ALL"] + ART_STYLE_KEYS)

# --- 2. BUILD THE QUERY ---
# Added: illustrator, rarity, market_price
query_str = """
    SELECT card_id, name, illustrator, rarity, market_price, image_url, art_style, labeled_by 
    FROM tcg_cards 
    WHERE REPLACE(supertype, 'é', 'e') = 'Pokemon' AND image_url IS NOT NULL
"""

if view_mode == "Unlabeled / Needs Review":
    query_str += " AND (art_style IS NULL OR art_style = '\"Manual review needed\"')"
else:
    if selected_style and selected_style != "ALL":
        query_str += f" AND art_style = '\"{selected_style}\"'"
    else:
        query_str += " AND art_style != '\"Manual review needed\"' AND art_style IS NOT NULL"

query_str += " LIMIT 24;"

with engine.connect() as conn:
    cards = conn.execute(text(query_str)).mappings().fetchall()

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
                
                # --- NEW EXPANDABLE METADATA SECTION ---
                with st.expander(f"📖 {card['name']} Details"):
                    
                    # Helper function to catch None, empty strings, spaces, and "Unknown"
                    def safe_display(val):
                        if not val or str(val).strip() in ["", "Unknown", "None"]:
                            return "⚠️ Missing"
                        return str(val)

                    st.markdown(f"**Current Supertype:** {safe_display(card.get('supertype'))}")
                    st.markdown(f"**Illustrator:** {safe_display(card.get('illustrator'))}")
                    st.markdown(f"**Rarity:** {safe_display(card.get('rarity'))}")
                    
                    price = card.get('market_price')
                    price_display = f"${price:.2f}" if price else "⚠️ Missing"
                    st.markdown(f"**Market Price:** {price_display}")
                    
                # Current status
                current_val = card['art_style']
                if isinstance(current_val, str) and current_val.startswith('"'):
                    try:
                        current_val = json.loads(current_val)
                    except:
                        pass
                idx = ART_STYLE_KEYS.index(current_val) if current_val in ART_STYLE_KEYS else 0
                
                # Dropdown
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
                
                # Save Label
                if st.button("Lock Anchor", key=f"btn_{card['card_id']}", type="primary", use_container_width=True):
                    with engine.begin() as conn:
                        conn.execute(text("""
                            UPDATE tcg_cards 
                            SET art_style = :style, labeled_by = 'Human_Audit'
                            WHERE card_id = :id
                        """), {
                            "style": json.dumps(new_style), 
                            "id": card['card_id']
                        })
                    st.rerun()