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

# ==========================================
# 1. CAMEO SWEEP STATE & FUNCTIONS
# ==========================================
if 'cameo_sweep_batch' not in st.session_state:
    st.session_state['cameo_sweep_batch'] = []

def fetch_cameo_sweep_batch(engine, limit=12):
    """Fetches cards that have a detected cameo frequency but no named pokemon."""
    query = text("""
        SELECT card_id, name, image_url, cameo_frequency, art_style
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
    """Saves the comma-separated string as a JSON array."""
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
            
        # UI Cleanup: Instantly remove the card from the screen
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
                
                # Show the AI's hint
                st.caption(f"🤖 AI Detected:  entities**")
                
                # Text Input for the names
                st.text_input(
                    "Cameo Pokémon:", 
                    placeholder="e.g. Pikachu, Eevee", 
                    key=f"sweep_cameo_{c_id}"
                )
                
                # Save button
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
            overall_df = pd.read_sql(overall_query, conn)
        
        # Melt for easy charting
        overall_melt = overall_df.melt(var_name="Category", value_name="Percentage")
        st.bar_chart(overall_melt.set_index("Category"))
        
    with col2:
        st.markdown("**Missing Illustrator by Art Style (Top 10 Worst Offenders)**")
        # Only looks at Human_Audited cards so the data isn't skewed by unverified styles
        genre_query = text("""
            SELECT 
                art_style::text as "Art Style",
                ROUND((COUNT(*) FILTER (WHERE illustrator IS NULL OR illustrator IN ('', 'Unknown', 'N/A')) * 100.0 / NULLIF(COUNT(*), 0)), 1) as "Missing %"
            FROM tcg_cards
            WHERE labeled_by = 'Human_Audit' 
              AND REPLACE(supertype, 'é', 'e') = 'Pokemon'
            GROUP BY art_style::text
            HAVING COUNT(*) > 5 -- Require at least a small sample size
            ORDER BY "Missing %" DESC
            LIMIT 10
        """)
        with engine.connect() as conn:
            genre_df = pd.read_sql(genre_query, conn)
            
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
        "Missing Cameo Pokémon" # <-- New Option Added
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
    # Identifies cards with a cameo count but no JSON data
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

# Added cameo_frequency and cameo_pokemon to the query so the UI can reference them
query = text(f"""
    SELECT card_id, name, image_url, illustrator, rarity, market_price, card_aesthetic, supertype, cameo_frequency, cameo_pokemon
    FROM tcg_cards
    WHERE ({sql_condition})
    LIMIT 24
""")

with engine.connect() as conn:
    cards = conn.execute(query).mappings().fetchall()

st.divider()

if not cards:
    st.success(f"🎉 No cards found with {missing_target}! Your database is perfectly clean for this metric.")
else:
    st.info(f"Displaying up to 24 cards requiring {target_column} updates.")
    cols = st.columns(4)
    for i, card in enumerate(cards):
        with cols[i % 4]:
            with st.container(border=True):
                st.image(card['image_url'], use_container_width=True)
                
                # --- BULLETPROOF EXPANDER ---
                with st.expander(f"📖 {card['name']} Details"):
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
                    
                    # Show the hint if we are specifically hunting cameos
                    if target_column == "cameo_pokemon":
                        st.markdown(f"🤖 **AI Detected:** {card.get('cameo_frequency')} background entities")
                
                # --- DYNAMIC INPUT UI ---
                new_val = None
                if target_column == "market_price":
                    new_val = st.number_input(f"New Price ($):", min_value=0.0, format="%.2f", key=f"input_{card['card_id']}")
                elif target_column == "card_aesthetic":
                    st.markdown("**Tag Aesthetics:**")
                    selected_aes = st.multiselect(
                        "Select Aesthetics:", 
                        options=AESTHETIC_KEYS, 
                        key=f"aes_{card['card_id']}"
                    )
                    new_val = json.dumps(selected_aes) if selected_aes else None
                elif target_column == "cameo_pokemon":
                    st.markdown("**Identify Cameos:**")
                    cameo_str = st.text_input("Cameo Pokémon (comma-separated):", key=f"cam_{card['card_id']}", placeholder="e.g. Pikachu, Eevee")
                    # Safely convert the string into a python list, then to JSON
                    new_val_list = [c.strip() for c in cameo_str.split(",")] if cameo_str.strip() else []
                    new_val = json.dumps(new_val_list) if new_val_list else None
                elif target_column != "supertype":
                    new_val = st.text_input(f"New {target_column.capitalize()}:", key=f"input_{card['card_id']}")
                
                # --- SUPERTYPE SELECTOR ---
                valid_supertypes = ["Pokemon", "Trainer", "Energy", "Item"]
                current_sup = card.get('supertype')
                if current_sup not in valid_supertypes:
                    current_sup = "Pokemon" 
                
                new_supertype = st.selectbox(
                    "Assign Supertype:" if target_column == "supertype" else "Supertype Override:", 
                    options=valid_supertypes,
                    index=valid_supertypes.index(current_sup),
                    key=f"sup_{card['card_id']}"
                )
                
                # --- SAVE LOGIC ---
                if st.button("Save Fix", key=f"save_{card['card_id']}", use_container_width=True, type="primary"):
                    with engine.begin() as conn:
                        if target_column == "supertype":
                            conn.execute(text("""
                                UPDATE tcg_cards
                                SET supertype = :supertype
                                WHERE card_id = :id
                            """), {"supertype": new_supertype, "id": card['card_id']})
                        elif target_column in ["card_aesthetic", "cameo_pokemon"]:
                            # Bypass the 'N/A' string assignment which breaks JSONB columns
                            conn.execute(text(f"""
                                UPDATE tcg_cards
                                SET {target_column} = :new_val, supertype = :supertype
                                WHERE card_id = :id
                            """), {"new_val": new_val, "supertype": new_supertype, "id": card['card_id']})
                        else:
                            # Standard logic for text/numeric columns
                            if new_val or new_val == 0.0:
                                conn.execute(text(f"""
                                    UPDATE tcg_cards
                                    SET {target_column} = :new_val, supertype = :supertype
                                    WHERE card_id = :id
                                """), {"new_val": new_val, "supertype": new_supertype, "id": card['card_id']})
                            else:
                                conn.execute(text(f"""
                                    UPDATE tcg_cards
                                    SET supertype = :supertype,
                                        {target_column} = 'N/A'
                                    WHERE card_id = :id
                                """), {"supertype": new_supertype, "id": card['card_id']})
                    st.rerun()

# ==========================================
# 4. RENDER NEW STATIONS & VISUALS
# ==========================================
# render_cameo_sweep_station(engine)
render_missing_data_visualizations()