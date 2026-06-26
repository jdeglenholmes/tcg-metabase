import sys
import os
import json

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

import streamlit as st
from sqlalchemy import text
from src.dashboard.utils import render_sidebar, get_engine

st.set_page_config(page_title="Data Healing", layout="wide")
render_sidebar()

st.title("🩹 Data Healing Station")
st.markdown("Resolve missing or 'Unknown' database attributes to maintain high-fidelity metadata.")

engine = get_engine()

# --- TARGET SELECTOR ---
missing_target = st.selectbox(
    "Select Missing Data Category to Resolve:",
    [
        "Missing Illustrator", 
        "Missing Rarity", 
        "Missing Market Price",
        "Missing Supertype",
        "Unreviewed Aesthetics (Cameos & Trainer Gallery)"
    ]
)

# Added empty string '' checks to ensure all invisible data is caught
if missing_target == "Missing Illustrator":
    sql_condition = "illustrator = 'Unknown' OR illustrator IS NULL OR illustrator = '' AND supertype = 'Pokemon' OR 'Pokémon'"
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
else:
    sql_condition = "card_aesthetic IS NULL OR card_aesthetic = ''"
    target_column = "card_aesthetic"

query = text(f"""
    SELECT card_id, name, image_url, illustrator, rarity, market_price, card_aesthetic, supertype
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
                
                # --- DYNAMIC INPUT UI ---
                new_val = None
                if target_column == "market_price":
                    new_val = st.number_input(f"New Price ($):", min_value=0.0, format="%.2f", key=f"input_{card['card_id']}")
                elif target_column == "card_aesthetic":
                    st.markdown("**Tag Aesthetics:**")
                    has_cameo = st.checkbox("Has Cameo", key=f"cam_{card['card_id']}")
                    is_tg = st.checkbox("Is Trainer Gallery", key=f"tg_{card['card_id']}")
                    aes_list = []
                    if has_cameo: aes_list.append("has_cameo")
                    if is_tg: aes_list.append("is_trainer_gallery")
                    new_val = json.dumps(aes_list)
                elif target_column != "supertype":
                    # Only show text input if we aren't explicitly fixing the supertype
                    new_val = st.text_input(f"New {target_column.capitalize()}:", key=f"input_{card['card_id']}")
                
                # --- SUPERTYPE SELECTOR ---
                valid_supertypes = ["Pokemon", "Trainer", "Energy", "Item"]
                current_sup = card.get('supertype')
                if current_sup not in valid_supertypes:
                    current_sup = "Pokemon" # Fallback if data is totally missing
                
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
                            # Standard save logic for the new Missing Supertype queue
                            conn.execute(text("""
                                UPDATE tcg_cards
                                SET supertype = :supertype
                                WHERE card_id = :id
                            """), {"supertype": new_supertype, "id": card['card_id']})
                        else:
                            # Override logic for all other queues
                            if new_val or new_val == 0.0 or new_val == "[]":
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