import sys
import os
import streamlit as st

# Setup paths
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from src.dashboard.utils import (
    get_engine, parse_json_array, fetch_card_batch, fetch_cameo_guesses,
    update_card_record, fetch_and_stitch_grid, fetch_and_rotate_image
)

# --- PAGE CONFIG ---
st.set_page_config(page_title="TCG Metabase App", layout="wide")

st.title("TCG Metabase App")
st.markdown("Enhance Cloud-based TCG Metdata in a Gallery-Style Layout")

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
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("🔄 Standard DB Fetch", type="primary", use_container_width=True):
        try:
            st.session_state['card_batch'] = fetch_card_batch(engine, search_input, display_limit)
        except Exception as e:
            st.error(f"Fetch Error: {e}")

# --- AI AUDIT CONTROL PANEL ---
with st.expander("🤖 Gemini Audit Settings & Modular Filters", expanded=True):
    a_col1, a_col2, a_col3, a_col4 = st.columns([1.5, 1.5, 1, 1])
    
    with a_col1:
        audit_mode_opt = st.selectbox(
            "Audit Strategy:",
            ["Discrepancies Only", "Agreements Only", "All Candidates"],
            index=0,
            help="Discrepancies = Find cards where DB label != Gemini prediction."
        )
    
    with a_col2:
        db_status_opt = st.selectbox(
            "Target DB Cameo Status:",
            ["TRUE", "FALSE", "NULL", "ALL"],
            index=0,
            help="Filter SQL query by current human_cameo state in database."
        )
        
    with a_col3:
        min_conf_opt = st.slider("Min Confidence:", 0.50, 1.00, 0.80, 0.05)
        
    with a_col4:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("⚡ Run AI Audit", type="secondary", use_container_width=True):
            with st.spinner("Executing modular SQL + Gemini Vision audit..."):
                try:
                    st.session_state['card_batch'] = fetch_cameo_guesses(
                        engine=engine,
                        limit=display_limit,
                        db_cameo_status=db_status_opt,
                        audit_mode=audit_mode_opt,
                        min_confidence=min_conf_opt
                    )
                except Exception as e:
                    st.error(f"Audit Error: {e}")

# --- MODAL REPORT VIEW ---
@st.dialog("Full Metadata Report", width="large")
def show_metadata_report(card):
    c_id = card['card_id']
    
    # Track rotation state in session_state for real-time UI updates inside the dialog
    if f"rot_{c_id}" not in st.session_state:
        st.session_state[f"rot_{c_id}"] = card.get('rotation_angle', 0)
    
    # Structure the UI into tabs
    tab_meta, tab_connect = st.tabs(["📝 Base Metadata", "🧩 Connections & Preview"])
    
    with tab_meta:
        col_img, col_meta = st.columns([1, 1.5])
        with col_img:
            current_rot = st.session_state[f"rot_{c_id}"]
            
            # Fetch and display the rotated image dynamically
            rotated_card_img = fetch_and_rotate_image(card['image_url'], current_rot)
            st.image(rotated_card_img, use_container_width=True)
            st.caption(f"**Card ID:** `{c_id}` | **Rotation:** `{current_rot}°`")
            
            # Rotation Button
            if st.button("↻ Rotate 90° Right", key=f"btn_rot_{c_id}", use_container_width=True):
                st.session_state[f"rot_{c_id}"] = (current_rot + 90) % 360
                st.rerun()
            
        with col_meta:
            st.subheader(f"{card['name']}")
            st.text_input("Illustrator:", value=card.get('illustrator') or "", key=f"ill_{c_id}")
            st.text_input("Rarity:", value=card.get('rarity') or "", key=f"rar_{c_id}")
            
            current_price = card.get('market_price')
            st.number_input("Price ($):", value=float(current_price) if current_price else 0.00, step=0.50, key=f"price_{c_id}")

            # --- GEMINI PREDICTION DISPLAY ---
            if 'gemini_guess' in card:
                guess_str = "👤 Human Detected" if card['gemini_guess'] else "🚫 No Human"
                conf_pct = int(card['gemini_confidence'] * 100)
                st.info(f"**Gemini Suggestion:** {guess_str} ({conf_pct}% confidence)\n\n_{card['gemini_reasoning']}_")
            
            # Preserve existing DB value if present; fall back to Gemini's guess if human_cameo is NULL
            if card.get('human_cameo') is not None:
                default_cameo = bool(card.get('human_cameo'))
            else:
                default_cameo = bool(card.get('gemini_guess', False))

            st.checkbox("Is Trainer?", value=bool(card.get('is_trainer')), key=f"trainer_{c_id}")
            st.checkbox("Human Cameo?", value=default_cameo, key=f"human_{c_id}") # ADDED
            st.checkbox("Is Shiny?", value=bool(card.get('is_shiny')), key=f"shiny_{c_id}")
            st.divider()
            st.markdown("**Entity Tracking**")
            st.number_input("Cameo Count:", value=int(card.get('cameo_frequency') or 0), min_value=0, key=f"cameo_freq_{c_id}")
            
            current_cameos = [c for c in parse_json_array(card.get('cameo_pokemon')) if c is not None]
            st.text_input("Cameo Pokémon (comma-separated):", value=", ".join(current_cameos), key=f"cameo_names_{c_id}", placeholder="e.g. Pikachu, Eevee")
    
    with tab_connect:
        st.markdown("**🧩 Physical Connection (Mural/Grid)**")
        st.caption("ℹ️️ *For infinitely recurring/tiling cards, set all grid and position values to 0.*")
        p_col1, p_col2 = st.columns([1.5, 1])

        with p_col1:
            phys_group = st.text_input("Grid Group Name:", value=card.get('phys_group') or "", placeholder="e.g., Mewtwo V-UNION", key=f"p_grp_{c_id}")
            
        with p_col2:
            def_w = int(card.get('grid_width')) if card.get('grid_width') is not None else 1
            def_h = int(card.get('grid_height')) if card.get('grid_height') is not None else 1
            def_x = int(card.get('position_x')) if card.get('position_x') is not None else 1
            def_y = int(card.get('position_y')) if card.get('position_y') is not None else 1

            grid_w = st.number_input("Total Columns (Width):", min_value=0, max_value=5, value=def_w, key=f"p_gw_{c_id}")
            grid_h = st.number_input("Total Rows (Height):", min_value=0, max_value=5, value=def_h, key=f"p_gh_{c_id}")
            pos_x = st.number_input("My Column Position (X):", min_value=0, max_value=5, value=def_x, key=f"p_x_{c_id}")
            pos_y = st.number_input("My Row Position (Y):", min_value=0, max_value=5, value=def_y, key=f"p_y_{c_id}")
            
        st.divider()
        st.markdown("**📖 Narrative Connection (Storyline)**")
        n_col1, n_col2 = st.columns([1.5, 1])

        with n_col1:
            story_name = st.text_input("Story Name:", value=card.get('story_name') or "", placeholder="e.g., Charizard vs Venusaur Battle", key=f"n_st_{c_id}")
            
        with n_col2:
            seq_order = st.number_input("Sequence Order:", min_value=1, value=int(card.get('sequence_order') or 1), key=f"n_seq_{c_id}")
            
            role_options = ["Start", "Middle", "End"]
            current_role = card.get('narrative_role') or "Start"
            role_idx = role_options.index(current_role) if current_role in role_options else 0
            st.selectbox("Role in Story:", role_options, index=role_idx, key=f"n_role_{c_id}")

        st.divider()
        if phys_group:
            st.markdown(f"**Live Preview: {phys_group}**")
            if st.button("🎨 Render Stitched Image", key=f"render_{c_id}"):
                with st.spinner("Downloading, rotating, and stitching assets..."):
                    stitched_canvas = fetch_and_stitch_grid(engine, phys_group)
                    if stitched_canvas:
                        st.image(stitched_canvas)
                    else:
                        st.warning("No grid pieces found in database for this group.")

    st.divider()
    # Save button handles data from both tabs
    if st.button("💾 Save All Data", key=f"save_{c_id}", type="primary", use_container_width=True):
        cameo_str = st.session_state[f"cameo_names_{c_id}"]
        
        update_data = {
            "illustrator": st.session_state[f"ill_{c_id}"],
            "rarity": st.session_state[f"rar_{c_id}"],
            "price": st.session_state[f"price_{c_id}"],
            "trainer": st.session_state[f"trainer_{c_id}"],
            "human_cameo": st.session_state[f"human_{c_id}"], # ADDED
            "cameo_freq": st.session_state[f"cameo_freq_{c_id}"],
            "cameo_names": [c.strip() for c in cameo_str.split(",")] if cameo_str.strip() else [],
            "shiny": st.session_state[f"shiny_{c_id}"],
            "rotation_angle": st.session_state[f"rot_{c_id}"],
            "phys_group": st.session_state[f"p_grp_{c_id}"].strip(),
            "grid_w": st.session_state[f"p_gw_{c_id}"],
            "grid_h": st.session_state[f"p_gh_{c_id}"],
            "pos_x": st.session_state[f"p_x_{c_id}"],
            "pos_y": st.session_state[f"p_y_{c_id}"],
            "story_name": st.session_state[f"n_st_{c_id}"].strip(),
            "seq_order": st.session_state[f"n_seq_{c_id}"],
            "narr_role": st.session_state[f"n_role_{c_id}"]
        }
        
        try:
            update_card_record(engine, c_id, update_data)
            
            for c in st.session_state['card_batch']:
                if c['card_id'] == c_id:
                    c.update({
                        'illustrator': update_data["illustrator"],
                        'rarity': update_data["rarity"],
                        'market_price': update_data["price"],
                        'is_trainer': update_data["trainer"],
                        'human_cameo': update_data["human_cameo"],
                        'cameo_frequency': update_data["cameo_freq"],
                        'cameo_pokemon': update_data["cameo_names"] if update_data["cameo_names"] else None,
                        'is_shiny': update_data["shiny"],
                        'rotation_angle': update_data["rotation_angle"],
                        'phys_group': update_data["phys_group"] if update_data["phys_group"] else None,
                        'grid_width': update_data["grid_w"],
                        'grid_height': update_data["grid_h"],
                        'position_x': update_data["pos_x"],
                        'position_y': update_data["pos_y"],
                        'story_name': update_data["story_name"] if update_data["story_name"] else None,
                        'sequence_order': update_data["seq_order"],
                        'narrative_role': update_data["narr_role"]
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
                # Render gallery card image with rotation applied
                card_rot = card.get('rotation_angle', 0)
                display_img = fetch_and_rotate_image(card['image_url'], card_rot) if card_rot > 0 else card['image_url']
                st.image(display_img, use_container_width=True)
                
                info_col1, info_col2 = st.columns(2)
                with info_col1:
                    display_id = card.get('position_id') or card.get('card_id')
                    st.caption(f"`{display_id}`")
                with info_col2:
                    set_name = card.get('set_name') or "Unknown"
                    st.caption(f"*{set_name}*")
                
                if st.button("🔍 Inspect", key=f"inspect_{card['card_id']}", use_container_width=True):
                    show_metadata_report(card)