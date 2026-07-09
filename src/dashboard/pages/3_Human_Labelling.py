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

# Ensure AESTHETIC_KEYS is added to your utils.py!
from src.dashboard.utils import render_sidebar, get_engine, ART_STYLE_KEYS, AESTHETIC_KEYS

class AppraisalResult(BaseModel):
    style: str = Field(description="The exact name of the selected art style category.")
    reason: str = Field(description="A brief, 1-sentence justification.")

st.set_page_config(page_title="Central Auditor", layout="wide")
render_sidebar()

st.title("⚖️ Central Auditor (Active Learning)")
st.markdown("Edit metadata, apply styles and aesthetics, and lock in human anchors.")

engine = get_engine()

# --- OPTIMIZED HELPERS ---
def parse_json_array(raw_val):
    """Safely extracts a full JSON array for multiselect widgets."""
    if not raw_val: return []
    try:
        parsed = json.loads(raw_val)
        return parsed if isinstance(parsed, list) else [parsed]
    except:
        return [str(raw_val).strip('[]"\' ')]
    
def parse_json_column(raw_val, fallback):
    """Safely extracts the first item from a JSON array column."""
    if not raw_val: return fallback
    try:
        parsed = json.loads(raw_val)
        return parsed[0] if isinstance(parsed, list) and len(parsed) > 0 else parsed
    except: 
        # Clean up any trailing spaces or quotes that might break the dropdown index
        return str(raw_val).strip('[]"\' ')

# --- STATE MANAGEMENT ---
if 'card_batch' not in st.session_state:
    st.session_state['card_batch'] = []

# --- DATA FETCHING ---
def load_new_batch(mode, style, search, limit):
    # Added is_trainer, is_cameo, and card_aesthetics to the fetch
    base_query = """
        SELECT card_id, name, illustrator, rarity, market_price, image_url, 
               art_style, card_aesthetic, has_trainer, cameos
        FROM tcg_cards 
        WHERE REPLACE(supertype, 'é', 'e') = 'Pokemon' AND image_url IS NOT NULL
    """
    params = {}
    
    if mode == "Unlabeled / Needs Review":
        base_query += " AND (labeled_by IS NULL OR labeled_by != 'Human_Audit')"
    elif mode == "Currently Labeled":
        base_query += " AND labeled_by = 'Human_Audit'"
        if style and style != "ALL":
            base_query += " AND art_style @> :style"
            params["style"] = json.dumps([style])
    elif mode == "Find Specific Card" and search:
        base_query += " AND (name ILIKE :s OR card_id ILIKE :s)"
        params["s"] = f"%{search}%"
        
    base_query += " ORDER BY RANDOM() LIMIT :limit"
    params["limit"] = limit
    
    try:
        with engine.connect() as conn:
            results = conn.execute(text(base_query), params).mappings().fetchall()
            st.session_state['card_batch'] = [dict(c) for c in results]
    except Exception as e:
        st.error(f"Database Fetch Error: {e}")

# --- CALLBACK: SAVE ALL DATA ---
def save_card_data(card_id, current_view):
    # Retrieve all the inputs from session state using their specific keys
    new_style = st.session_state[f"style_{card_id}"]
    new_aesthetics_list = st.session_state[f"aesthetic_{card_id}"]
    new_illustrator = st.session_state[f"ill_{card_id}"]
    new_rarity = st.session_state[f"rar_{card_id}"]
    new_price = st.session_state[f"price_{card_id}"]
    new_trainer = st.session_state[f"trainer_{card_id}"]
    new_cameo = st.session_state[f"cameo_{card_id}"]
    
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                UPDATE tcg_cards 
                SET art_style = :style, 
                    card_aesthetic = :aesthetic,
                    illustrator = :illustrator,
                    rarity = :rarity,
                    market_price = :price,
                    has_trainer = :trainer,
                    cameos = :cameo,
                    labeled_by = 'Human_Audit', 
                    updated_at = CURRENT_TIMESTAMP
                WHERE card_id = :id
            """), {
                "style": json.dumps([new_style]),
                "aesthetic": json.dumps(new_aesthetics_list) if new_aesthetics_list and new_aesthetics_list != "None" else None,
                "illustrator": new_illustrator if new_illustrator else None,
                "rarity": new_rarity if new_rarity else None,
                "price": new_price if new_price > 0 else None,
                "trainer": new_trainer,
                "cameo": new_cameo,
                "id": card_id
            })
            
        # UI Cleanup
        if current_view == "Unlabeled / Needs Review":
            st.session_state['card_batch'] = [c for c in st.session_state['card_batch'] if c['card_id'] != card_id]
        else:
            for card in st.session_state['card_batch']:
                if card['card_id'] == card_id:
                    card['art_style'] = json.dumps([new_style])
                    card['card_aesthetic'] = json.dumps(new_aesthetics_list)
                    card['illustrator'] = new_illustrator
                    card['rarity'] = new_rarity
                    card['market_price'] = new_price
                    card['has_trainer'] = new_trainer
                    card['cameos'] = new_cameo
                    break
                    
        st.toast(f"✅ Master record saved for {card_id}!")
    except Exception as e:
        st.error(f"Database Save Error: {e}")

# --- UI CONTROLS ---
col1, col2, col3, col4 = st.columns([2, 2, 1, 1.5])
with col1:
    view_mode = st.radio("View Mode:", ["Unlabeled / Needs Review", "Currently Labeled", "Find Specific Card"])
with col2:
    style_filter = st.selectbox("Style:", ["ALL"] + ART_STYLE_KEYS) if view_mode == "Currently Labeled" else None
    search_input = st.text_input("Search:") if view_mode == "Find Specific Card" else None
with col3:
    display_limit = st.number_input("Limit:", 4, 100, 24, 4)
with col4:
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("🔄 Fetch New Batch", type="primary", use_container_width=True):
        load_new_batch(view_mode, style_filter, search_input, display_limit)

# --- RENDER GRID ---
st.divider()

cards = st.session_state.get('card_batch', [])

if not cards:
    st.info("No cards currently loaded. Click 'Fetch New Batch' to begin auditing.")
else:
    cols = st.columns(4)
    for i, card in enumerate(cards):
        c_id = card['card_id']
        with cols[i % 4]:
            with st.container(border=True):
                st.image(card['image_url'], use_container_width=True)
                
                # --- EDITABLE METADATA EXPANDER ---
                with st.expander(f"📖 {card['name']} (Edit Data)"):
                    st.text_input("Illustrator:", value=card.get('illustrator') or "", key=f"ill_{c_id}")
                    st.text_input("Rarity:", value=card.get('rarity') or "", key=f"rar_{c_id}")
                    
                    current_price = card.get('market_price')
                    st.number_input("Price ($):", value=float(current_price) if current_price else 0.00, step=0.50, key=f"price_{c_id}")
                    
                    # Boolean flags for Cameos and Trainers
                    st.checkbox("Is Trainer?", value=bool(card.get('has_trainer')), key=f"trainer_{c_id}")
                    st.checkbox("Is Cameo?", value=bool(card.get('cameos')), key=f"cameo_{c_id}")
                    
                    # Display the current recorded style as text for reference
                    current_style_val = parse_json_column(card.get('art_style'), "None")
                    st.info(f"Currently saved style: **{current_style_val}**")

                # --- CLASSIFICATION DROPDOWNS ---
                # Art Style
                idx_style = ART_STYLE_KEYS.index(current_style_val) if current_style_val in ART_STYLE_KEYS else 0
                st.selectbox(
                    "Art Style:", 
                    options=ART_STYLE_KEYS, 
                    index=idx_style,
                    key=f"style_{c_id}"
                )
                
                # Card Aesthetics (Upgraded to Multiselect)
                current_aes_list = parse_json_array(card.get('card_aesthetic'))
                
                # Ensure the current values actually exist in your options list to prevent errors
                valid_defaults = [aes for aes in current_aes_list if aes in AESTHETIC_KEYS]
                
                st.multiselect(
                    "Card Aesthetics:", 
                    options=AESTHETIC_KEYS, 
                    default=valid_defaults, # Multiselect uses 'default' instead of 'index'
                    key=f"aesthetic_{c_id}"
                )
                
                # --- MASTER SAVE BUTTON ---
                if st.button("💾 Save Data", key=f"save_{c_id}", type="primary", use_container_width=True):
                    save_card_data(c_id, view_mode)
                    st.rerun() # Force a quick rerun to clear the visual if needed
                
                # --- GEMINI ADVISOR ---
                if st.button("🤖 Ask Gemini", key=f"gemini_{c_id}", use_container_width=True):
                    with st.spinner("Analyzing..."):
                        try:
                            client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
                            img = Image.open(BytesIO(requests.get(card['image_url']).content))
                            resp = client.models.generate_content(
                                model='gemini-3.1-flash',
                                contents=[f"Classify this into ONE style: {ART_STYLE_KEYS} and ONE aesthetic: {AESTHETIC_KEYS}", img],
                                config={"temperature": 0.0, "response_mime_type": "application/json", "response_schema": AppraisalResult}
                            )
                            ai = AppraisalResult.model_validate_json(resp.text)
                            st.success(f"**Style:** {ai.style}")
                            st.caption(ai.reason)
                        except Exception as e:
                            st.error(f"API Error: {e}")