import sys
import os
import requests
from io import BytesIO
from PIL import Image
import streamlit as st
from pydantic import BaseModel, Field
from google import genai

# Setup paths (Adjusted for app.py being in the root directory)
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from src.dashboard.utils import (
    get_engine, ART_STYLE_KEYS, AESTHETIC_KEYS,
    parse_json_array, parse_json_column, fetch_card_batch, update_card_record
)

class AppraisalResult(BaseModel):
    style: str = Field(description="The exact name of the selected art style category.")
    aesthetic: str = Field(description="The exact name of the selected card aesthetic category.")
    reason: str = Field(description="A brief, 1-sentence justification.")

# --- PAGE CONFIG ---
st.set_page_config(page_title="Central Auditor", layout="wide")

st.title("⚖️ Central Auditor")
st.markdown("Edit metadata, log cameo appearances, and lock in human anchors.")

engine = get_engine()

# --- STATE MANAGEMENT ---
if 'card_batch' not in st.session_state:
    st.session_state['card_batch'] = []

# --- UI CONTROLS & FILTER RIBBON ---
col1, col2, col3 = st.columns([3, 1, 1.5])

with col1:
    search_input = st.text_input("🔍 Search Name or ID:")

with col2:
    display_limit = st.number_input("Limit:", 4, 100, 24, 4)

with col3:
    st.markdown("<br><br>", unsafe_allow_html=True)
    if st.button("🔄 Fetch New Batch", type="primary", use_container_width=True):
        try:
            results = fetch_card_batch(engine, search_input, display_limit)
            st.session_state['card_batch'] = results
        except Exception as e:
            st.error(f"Database Fetch Error: {e}")

# --- MODAL REPORT VIEW ---
@st.dialog("Full Metadata Report", width="large")
def show_metadata_report(card):
    c_id = card['card_id']
    
    col_img, col_meta = st.columns([1, 1.5])
    
    with col_img:
        st.image(card['image_url'], use_container_width=True)
        st.caption(f"**Card ID:** `{c_id}`")
        
    with col_meta:
        st.subheader(f"{card['name']}")
        
        st.text_input("Illustrator:", value=card.get('illustrator') or "", key=f"ill_{c_id}")
        st.text_input("Rarity:", value=card.get('rarity') or "", key=f"rar_{c_id}")
        
        current_price = card.get('market_price')
        st.number_input("Price ($):", value=float(current_price) if current_price else 0.00, step=0.50, key=f"price_{c_id}")
        st.checkbox("Is Trainer?", value=bool(card.get('has_trainer')), key=f"trainer_{c_id}")
        
        st.divider()
        st.markdown("**Entity Tracking**")
        st.number_input("Cameo Count:", value=int(card.get('cameo_frequency') or 0), min_value=0, key=f"cameo_freq_{c_id}")
        
        current_cameos = [c for c in parse_json_array(card.get('cameo_pokemon')) if c is not None]
        st.text_input("Cameo Pokémon (comma-separated):", value=", ".join(current_cameos), key=f"cameo_names_{c_id}", placeholder="e.g. Pikachu, Eevee")
        
        st.divider()
        current_style = parse_json_column(card.get('art_style'), "None")
        idx_style = ART_STYLE_KEYS.index(current_style) if current_style in ART_STYLE_KEYS else 0
        
        st.info(f"Currently saved style: **{current_style}**")
        st.selectbox("Art Style:", options=ART_STYLE_KEYS, index=idx_style, key=f"style_{c_id}")
        
        valid_defaults = [aes for aes in parse_json_array(card.get('card_aesthetic')) if aes in AESTHETIC_KEYS]
        st.multiselect("Card Aesthetics:", options=AESTHETIC_KEYS, default=valid_defaults, key=f"aesthetic_{c_id}")
        
        st.divider()
        
        btn_col1, btn_col2 = st.columns(2)
        with btn_col1:
            if st.button("💾 Save Data", key=f"save_{c_id}", type="primary", use_container_width=True):
                cameo_str = st.session_state[f"cameo_names_{c_id}"]
                
                update_data = {
                    "style": st.session_state[f"style_{c_id}"],
                    "aesthetic": st.session_state[f"aesthetic_{c_id}"],
                    "illustrator": st.session_state[f"ill_{c_id}"],
                    "rarity": st.session_state[f"rar_{c_id}"],
                    "price": st.session_state[f"price_{c_id}"],
                    "trainer": st.session_state[f"trainer_{c_id}"],
                    "cameo_freq": st.session_state[f"cameo_freq_{c_id}"],
                    "cameo_names": [c.strip() for c in cameo_str.split(",")] if cameo_str.strip() else []
                }
                
                try:
                    update_card_record(engine, c_id, update_data)
                    for c in st.session_state['card_batch']:
                        if c['card_id'] == c_id:
                            c.update({
                                'art_style': f'["{update_data["style"]}"]',
                                'card_aesthetic': str(update_data["aesthetic"]).replace("'", '"'),
                                'illustrator': update_data["illustrator"],
                                'rarity': update_data["rarity"],
                                'market_price': update_data["price"],
                                'has_trainer': update_data["trainer"],
                                'cameo_frequency': update_data["cameo_freq"],
                                'cameo_pokemon': str(update_data["cameo_names"]).replace("'", '"') if update_data["cameo_names"] else None
                                })
                            break
                    st.rerun()
                except Exception as e:
                    st.error(f"Database Save Error: {e}")

        with btn_col2:
            if st.button("🤖 Ask Gemini", key=f"gemini_{c_id}", use_container_width=True):
                with st.spinner("Analyzing..."):
                    try:
                        client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
                        img = Image.open(BytesIO(requests.get(card['image_url']).content))
                        resp = client.models.generate_content(
                            model='gemini-2.5-flash',
                            contents=[f"Classify this into ONE style: {ART_STYLE_KEYS} and ONE aesthetic: {AESTHETIC_KEYS}", img],
                            config={"temperature": 0.0, "response_mime_type": "application/json", "response_schema": AppraisalResult}
                        )
                        ai = AppraisalResult.model_validate_json(resp.text)
                        st.success(f"**Style:** {ai.style} | **Aesthetic:** {ai.aesthetic}")
                        st.caption(ai.reason)
                    except Exception as e:
                        st.error(f"API Error: {e}")

# --- RENDER GALLERY ---
st.divider()

cards = st.session_state.get('card_batch', [])

if not cards:
    st.info("No cards currently loaded. Adjust filters and click 'Fetch New Batch'.")
else:
    cols = st.columns(4)
    for i, card in enumerate(cards):
        with cols[i % 4]:
            with st.container(border=True):
                st.image(card['image_url'], use_container_width=True)
                if st.button(f"🔍 Inspect {card['name']}", key=f"inspect_{card['card_id']}", use_container_width=True):
                    show_metadata_report(card)