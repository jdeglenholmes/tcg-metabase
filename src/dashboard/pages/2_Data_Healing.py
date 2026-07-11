import sys
import os
import json
import pandas as pd

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

import streamlit as st
from sqlalchemy import text
from src.dashboard.utils import render_sidebar, get_engine, AESTHETIC_KEYS

st.set_page_config(page_title="Data Healing", layout="wide")
render_sidebar()

st.title("🩹 Data Healing Station")
st.markdown("Resolve missing or 'Unknown' database attributes to maintain high-fidelity metadata.")

engine = get_engine()

# --- HELPER FUNCTION ---
def parse_json_array(raw_val):
    """Safely extracts a full JSON array. Handles PostgreSQL 'null' strings."""
    if not raw_val or str(raw_val).lower() == 'null': return []
    if isinstance(raw_val, list): return raw_val 
    try:
        parsed = json.loads(raw_val)
        return parsed if isinstance(parsed, list) else [parsed]
    except:
        return [str(raw_val).strip('[]"\' ')]

# ==========================================
# 1. CAMEO SWEEP STATE & FUNCTIONS
# ==========================================
if 'cameo_sweep_batch' not in st.session_state:
    st.session_state['cameo_sweep_batch'] = []

def fetch_cameo_sweep_batch(engine, limit=12):
    # Added ::text casting to protect the database driver
    query = text("""
        SELECT card_id, name, image_url, cameo_frequency, art_style::text as art_style
        FROM tcg_cards
        WHERE REPLACE(supertype, 'é', 'e') = 'Pokemon'
          AND image_url IS NOT NULL
          AND cameo_frequency > 0 
          AND (cameo_pokemon IS NULL OR cameo_pokemon::text = '[]' OR cameo_pokemon::text = 'null')
        ORDER BY RANDOM()
        LIMIT :limit
    """)
    try:
        with engine.connect() as conn:
            results = conn.execute(query, {"limit": limit}).mappings().fetchall()
            st.session_state['cameo_sweep_batch'] = [dict(c) for c in results]
    except Exception as e:
        st.error(f"Database Fetch Error: {e}")

def save_cameo_tags(engine, card_id):
    cameo_str = st.session_state[f"sweep_cameo_{card_id}"]
    new_cameos_list = [c.strip() for c in cameo_str.split(",")] if cameo_str.strip() else []
    
    if not new_cameos_list:
        st.warning("Please enter at least one Pokémon name, or set frequency to 0 in the Auditor.")
        return

    try:
        with engine.begin() as conn:
            conn.execute(text("""
                UPDATE tcg_cards 
                SET cameo_pokemon = :cameo_names,
                    updated_at = CURRENT_TIMESTAMP
                WHERE card_id = :id
            """), {
                "cameo_names": json.dumps(new_cameos_list),
                "id": card_id
            })
            
        st.session_state['cameo_sweep_batch'] = [
            c for c in st.session_state['cameo_sweep_batch'] if c['card_id'] != card_id
        ]
        st.toast(f"✅ Saved cameos for {card_id}!")
    except Exception as e:
        st.error(f"Database Save Error: {e}")

def render_cameo_sweep_station(engine):
    st.divider()
    st.subheader("🕵️ Cameo Identification Sweep")
    st.markdown("These cards were flagged by the AI as having background entities, but lack human-verified names.")

    col1, col2 = st.columns([1, 5])
    with col1:
        if st.button("🔄 Fetch Cameo Queue", type="primary"):
            fetch_cameo_sweep_batch(engine, 12)
            
    cards = st.session_state.get('cameo_sweep_batch', [])
    
    if not cards:
        st.info("Queue is empty. Click Fetch to find missing cameo data.")
        return

    cols = st.columns(4)
    for i, card in enumerate(cards):
        c_id = card['card_id']
        with cols[i % 4]:
            with st.container(border=True):
                st.image(card['image_url'], use_container_width=True)
                st.markdown(f"")
                
                st.caption(f"🤖 AI Detected: {card.get('cameo_frequency')} entities")
                
                st.text_input(
                    "Cameo Pokémon:", 
                    placeholder="e.g. Pikachu, Eevee", 
                    key=f"sweep_cameo_{c_id}"
                )
                
                if st.button("💾 Lock Cameos", key=f"sweep_save_{c_id}", use_container_width=True):
                    save_cameo_tags(engine, c_id)
                    st.rerun()

# ==========================================
# 2. VISUALIZATION COMPONENT
# ==========================================
def render_missing_data_visualizations():
    engine = get_engine()
    
    st.divider()
    st.subheader("📊 Missing Metadata Landscape")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("**Overall Missing Data**")
        overall_query = text("""
            SELECT 
                ROUND((COUNT(*) FILTER (WHERE illustrator IS NULL OR illustrator IN ('', 'Unknown', 'N/A')) * 100.0 / NULLIF(COUNT(*), 0)), 1) as "Missing Illustrator %",
                ROUND((COUNT(*) FILTER (WHERE market_price IS NULL OR market_price = 0) * 100.0 / NULLIF(COUNT(*), 0)), 1) as "Missing Price %",
                ROUND((COUNT(*) FILTER (WHERE rarity IS NULL OR rarity IN ('', 'Unknown', 'N/A')) * 100.0 / NULLIF(COUNT(*), 0)), 1) as "Missing Rarity %"
            FROM tcg_cards
            WHERE REPLACE(supertype, 'é', 'e') = 'Pokemon'
        """)
        with engine.connect() as conn:
            results = conn.execute(overall_query).mappings().fetchall()
            overall_df = pd.DataFrame([dict(r) for r in results])
        
        if not overall_df.empty:
            overall_melt = overall_df.melt(var_name="Category", value_name="Percentage")
            st.bar_chart(overall_melt.set_index("Category"))
        
    with col2:
        st.markdown("**Missing Illustrator by Art Style (Top 10 Worst Offenders)**")
        genre_query = text("""
            SELECT 
                art_style::text as "Art Style",
                ROUND((COUNT(*) FILTER (WHERE illustrator IS NULL OR illustrator IN ('', 'Unknown', 'N/A')) * 100.0 / NULLIF(COUNT(*), 0)), 1) as "Missing %"
            FROM tcg_cards
            WHERE labeled_by = 'Human_Audit' 
              AND REPLACE(supertype, 'é', 'e') = 'Pokemon'
            GROUP BY art_style::text
            HAVING COUNT(*) > 5 
            ORDER BY "Missing %" DESC
            LIMIT 10
        """)
        with engine.connect() as conn:
            results2 = conn.execute(genre_query).mappings().fetchall()
            genre_df = pd.DataFrame([dict(r) for r in results2])
            
        if not genre_df.empty:
            st.bar_chart(genre_df.set_index("Art Style"))
        else:
            st.info("Not enough audited data to generate genre breakdown.")


# ==========================================
# 3. LEGACY TARGET SELECTOR (Standard Healing)
# ==========================================
missing_target = st.selectbox(
    "Select Missing Data Category to Resolve:",
    [
        "Missing Illustrator", 
        "Missing Rarity", 
        "Missing Market Price",
        "Missing Supertype",
        "Missing Card Aesthetics",
        "Missing Cameo Pokémon" 
    ]
)

if missing_target == "Missing Illustrator":
    sql_condition = "(illustrator = 'Unknown' OR illustrator IS NULL OR illustrator = '') AND supertype IN ('Pokemon', 'Pokémon')"
    target_column = "illustrator"
elif missing_target == "Missing Rarity":
    sql_condition = "rarity = 'Unknown' OR rarity IS NULL OR rarity = ''"
    target_column = "rarity"
elif missing_target == "Missing Market Price":
    sql_condition = "market_price IS NULL"
    target_column = "market_price"
elif missing_target == "Missing Supertype":
    sql_condition = "supertype = 'Unknown' OR supertype IS NULL OR supertype = ''"
    target_column = "supertype"
elif missing_target == "Missing Cameo Pokémon":
    sql_condition = """
    cameo_frequency > 0 AND
    supertype = 'Pokemon' AND
    (cameo_pokemon IS NULL OR cameo_pokemon::text = '[]' OR cameo_pokemon::text = 'null')
    """
    target_column = "cameo_pokemon"
else:
    sql_condition = """
    supertype = 'Pokemon' AND 
    (card_aesthetic IS NULL OR card_aesthetic::text = '[]' OR card_aesthetic::text = 'null')
    """
    target_column = "card_aesthetic"

# Critical Fix 1: Cast JSON columns to text to prevent memory corruption
# Critical Fix 2: Added ORDER BY card_id to prevent grid reshuffling on widget interaction
query = text(f"""
    SELECT card_id, name, image_url, illustrator, rarity, market_price, 
           card_aesthetic::text as card_aesthetic, 
           supertype, cameo_frequency, 
           cameo_pokemon::text as cameo_pokemon
    FROM tcg_cards
    WHERE ({sql_condition})
    ORDER BY card_id 
    LIMIT 24
""")

with engine.connect() as conn:
    # Explicitly convert to standard Python dicts immediately
    cards = [dict(c) for c in conn.execute(query).mappings().fetchall()]

st.divider()

if not cards:
    st.success(f"🎉 No cards found with {missing_target}! Your database is perfectly clean for this metric.")
else:
    st.info(f"Displaying up to 24 cards requiring {target_column} updates.")
    cols = st.columns(4)
    for i, card in enumerate(cards):
        c_id = card['card_id']
        with cols[i % 4]:
            with st.container(border=True):
                st.image(card['image_url'], use_container_width=True)
                
                # --- EDITABLE METADATA EXPANDER ---
                with st.expander(f"📖 {card['name']} (Edit Data)"):
                    edit_ill = st.text_input("Illustrator:", value=card.get('illustrator') or "", key=f"ill_{c_id}")
                    edit_rar = st.text_input("Rarity:", value=card.get('rarity') or "", key=f"rar_{c_id}")
                    
                    current_price = card.get('market_price')
                    edit_price = st.number_input("Price ($):", value=float(current_price) if current_price else 0.00, step=0.50, key=f"price_{c_id}")
                    
                    edit_freq = st.number_input("Cameo Count:", value=int(card.get('cameo_frequency') or 0), min_value=0, key=f"freq_{c_id}")

                # --- TARGET-SPECIFIC UI ELEMENTS ---
                
                edit_aes = card.get('card_aesthetic')
                if edit_aes == 'null': edit_aes = None
                    
                edit_cameo_pkmn = card.get('cameo_pokemon')
                if edit_cameo_pkmn == 'null': edit_cameo_pkmn = None
                
                if target_column == "card_aesthetic":
                    st.markdown("**Tag Aesthetics:**")
                    current_aes_list = parse_json_array(card.get('card_aesthetic'))
                    valid_defaults = [aes for aes in current_aes_list if aes in AESTHETIC_KEYS]
                    
                    selected_aes = st.multiselect(
                        "Select Aesthetics:", 
                        options=AESTHETIC_KEYS, 
                        default=valid_defaults,
                        key=f"aes_{c_id}"
                    )
                    edit_aes = json.dumps(selected_aes) if selected_aes else None
                    
                elif target_column == "cameo_pokemon":
                    st.markdown("**Identify Cameos:**")
                    current_cameos = parse_json_array(card.get('cameo_pokemon'))
                    cameo_str_val = ", ".join([str(c) for c in current_cameos if c]) if current_cameos else ""
                    
                    cameo_str = st.text_input("Cameo Pokémon (comma-separated):", value=cameo_str_val, key=f"cam_{c_id}", placeholder="e.g. Pikachu, Eevee")
                    new_val_list = [c.strip() for c in cameo_str.split(",")] if cameo_str.strip() else []
                    edit_cameo_pkmn = json.dumps(new_val_list) if new_val_list else None

                # --- SUPERTYPE SELECTOR ---
                valid_supertypes = ["Pokemon", "Trainer", "Energy", "Item"]
                current_sup = card.get('supertype')
                if current_sup not in valid_supertypes:
                    current_sup = "Pokemon" 
                
                edit_sup = st.selectbox(
                    "Assign Supertype:" if target_column == "supertype" else "Supertype Override:", 
                    options=valid_supertypes,
                    index=valid_supertypes.index(current_sup),
                    key=f"sup_{c_id}"
                )
                
                # --- UNIFIED MASTER SAVE LOGIC ---
                if st.button("💾 Save All Changes", key=f"save_{c_id}", use_container_width=True, type="primary"):
                    with engine.begin() as conn:
                        conn.execute(text("""
                            UPDATE tcg_cards
                            SET illustrator = :ill,
                                rarity = :rar,
                                market_price = :price,
                                cameo_frequency = :freq,
                                supertype = :sup,
                                card_aesthetic = :aes,
                                cameo_pokemon = :cameo_pkmn,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE card_id = :id
                        """), {
                            "ill": edit_ill if edit_ill else None,
                            "rar": edit_rar if edit_rar else None,
                            "price": edit_price if edit_price > 0 else None,
                            "freq": edit_freq,
                            "sup": edit_sup,
                            "aes": edit_aes,
                            "cameo_pkmn": edit_cameo_pkmn,
                            "id": c_id
                        })
                    st.rerun()

# ==========================================
# 4. RENDER NEW STATIONS & VISUALS
# ==========================================
# render_cameo_sweep_station(engine)
render_missing_data_visualizations()