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
        "Unreviewed Aesthetics (Cameos & Trainer Gallery)" # NEW OPTION
    ]
)

if missing_target == "Missing Illustrator":
    sql_condition = "illustrator = 'Unknown' OR illustrator IS NULL"
    target_column = "illustrator"
elif missing_target == "Missing Rarity":
    sql_condition = "rarity = 'Unknown' OR rarity IS NULL"
    target_column = "rarity"
elif missing_target == "Missing Market Price":
    sql_condition = "market_price IS NULL"
    target_column = "market_price"
else:
    # Target cards that haven't had their aesthetic JSON array built yet
    sql_condition = "card_aesthetic IS NULL"
    target_column = "card_aesthetic"

# Added card_aesthetic to the SELECT statement
query = text(f"""
    SELECT card_id, name, image_url, illustrator, rarity, market_price, card_aesthetic
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
                
                with st.expander(f"📖 {card['name']} Details"):
                    st.markdown(f"Illustrator:")
                    st.markdown(f"Rarity:")
                    price_display = f"${card['market_price']:.2f}" if card['market_price'] else "N/A"
                    st.markdown(f"**Market Price:** {price_display}")
                
                # --- DYNAMIC INPUT UI ---
                if target_column == "market_price":
                    new_val = st.number_input(f"New Price ($):", min_value=0.0, format="%.2f", key=f"input_{card['card_id']}")
                
                elif target_column == "card_aesthetic":
                    # Special UI for boolean aesthetic tags
                    st.markdown("**Tag Aesthetics:**")
                    has_cameo = st.checkbox("Has Cameo", key=f"cam_{card['card_id']}")
                    is_tg = st.checkbox("Is Trainer Gallery", key=f"tg_{card['card_id']}")
                    
                    # Package them into a JSON array string
                    aes_list = []
                    if has_cameo: aes_list.append("has_cameo")
                    if is_tg: aes_list.append("is_trainer_gallery")
                    new_val = json.dumps(aes_list)
                    
                else:
                    new_val = st.text_input(f"New {target_column.capitalize()}:", key=f"input_{card['card_id']}")
                
                # --- SAVE LOGIC ---
                if st.button("Save Fix", key=f"save_{card['card_id']}", use_container_width=True, type="primary"):
                    # For aesthetics, we always want to save (even if empty string '[]') 
                    # so it clears from the queue.
                    if new_val or new_val == 0.0 or new_val == "[]":
                        with engine.begin() as conn:
                            conn.execute(text(f"""
                                UPDATE tcg_cards
                                SET {target_column} = :new_val
                                WHERE card_id = :id
                            """), {"new_val": new_val, "id": card['card_id']})
                        st.rerun()