import sys
import os
import streamlit as st

# Setup paths (Adjusted for app.py being in the root directory)
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from src.dashboard.utils import (
    get_engine, parse_json_array, fetch_card_batch, update_card_record
)

# --- PAGE CONFIG ---
st.set_page_config(page_title="PokeCheckr", layout="wide")


st.title("PokeCheckr")
st.markdown("Enhance Local Pokemon TCG Metdata viewed in a Gallery-Style Layout")

# --- DB CONNECTION---
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
        
        # Simplified button rendering
        if st.button("💾 Save Data", key=f"save_{c_id}", type="primary", use_container_width=True):
            cameo_str = st.session_state[f"cameo_names_{c_id}"]
            
            update_data = {
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
                # 1. The Card Image
                st.image(card['image_url'], use_container_width=True)
                
                # 2. Native Streamlit Text Layout
                st.markdown(f"**{card['name']}**")
                
                # Split the footer info into two native columns
                info_col1, info_col2 = st.columns(2)
                with info_col1:
                    # Uses the new position_id from your SQL, falls back to card_id
                    display_id = card.get('position_id') or card.get('card_id')
                    st.caption(f"`{display_id}`")
                
                with info_col2:
                    # Renders the set name in italics, aligned with Streamlit's native markdown
                    set_name = card.get('set_name') or "Unknown"
                    st.caption(f"*{set_name}*")
                
                # 3. The Native Inspect Button
                if st.button("🔍 Inspect", key=f"inspect_{card['card_id']}", use_container_width=True):
                    show_metadata_report(card)