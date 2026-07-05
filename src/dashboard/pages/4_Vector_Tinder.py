import sys
import os
import json
import streamlit as st
from sqlalchemy import text

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from src.dashboard.utils import render_sidebar, get_engine, ART_STYLE_KEYS

st.set_page_config(page_title="Vector Tinder", layout="wide")
render_sidebar()

st.title("🧲 Vector Tinder (Active Learning)")
st.markdown("Leverage `pgvector` math to instantly find the 24 closest visual matches to a seed style.")

engine = get_engine()

# --- OPTIMIZED HELPER FUNCTIONS ---
def safe_display(val):
    if not val or str(val).strip() in ["", "Unknown", "None"]:
        return "⚠️ Missing"
    return str(val)

# --- 1. SEED SELECTION ---
# UPDATED: Uses the global taxonomy list so all styles are visible
target_style = st.selectbox(
    "Select a Style to Hunt:", 
    options=ART_STYLE_KEYS,
    help="The engine will find one confirmed card of this style to use as a mathematical center."
)

st.divider()

# --- 2. VECTOR SEARCH EXECUTION ---
if st.button(f"🔍 Find visually similar cards for '{target_style}'", type="primary"):
    with engine.connect() as conn:
        # Step 1: Find a seed vector for the chosen style
        seed_query = text("""
            SELECT image_embedding 
            FROM tcg_cards 
            WHERE art_style @> :style_json 
              AND image_embedding IS NOT NULL 
              AND REPLACE(supertype, 'é', 'e') = 'Pokemon'
            LIMIT 1
        """)
        seed_result = conn.execute(seed_query, {"style_json": json.dumps([target_style])}).fetchone()
        
        if not seed_result:
            st.error(f"❌ No ground truth exists for `{target_style}` yet. Please manually assign this style to at least one card in the Central Auditor before searching.")
        else:
            seed_vector = seed_result[0]
            
            # Step 2: Perform the nearest-neighbor search against unlabeled/ambiguous cards
            search_query = text("""
                SELECT card_id, name, illustrator, rarity, market_price, image_url 
                FROM tcg_cards
                WHERE image_embedding IS NOT NULL
                  AND REPLACE(supertype, 'é', 'e') = 'Pokemon'
                  AND (art_style IS NULL OR art_style::text = '\"Manual review needed\"' OR art_style::text = '[\"Manual review needed\"]')
                ORDER BY image_embedding <-> :seed_vec::vector
                LIMIT 24
            """)
            
            # Format the vector array for pgvector
            formatted_vector = f"[{','.join(map(str, seed_vector))}]"
            try:
                candidates = conn.execute(search_query, {"seed_vec": formatted_vector}).mappings().fetchall()
            except Exception as e:
                st.error(f"Database Error: {e}")
                # This will print the actual PostgreSQL error, like "operator does not exist..."
                st.stop()
            # Store results in session state so they survive button clicks
            st.session_state['tinder_candidates'] = candidates
            st.session_state['tinder_target'] = target_style

# --- 3. RAPID CONFIRMATION UI ---
if 'tinder_candidates' in st.session_state and st.session_state['tinder_candidates']:
    target = st.session_state['tinder_target']
    candidates = st.session_state['tinder_candidates']
    
    st.success(f"🎯 Displaying top 24 mathematical matches for **{target}**")
    
    cols = st.columns(4)
    for i, card in enumerate(candidates):
        with cols[i % 4]:
            with st.container(border=True):
                st.image(card['image_url'], use_container_width=True)
                
                with st.expander(f"📖 {card['name']} Details"):
                    st.markdown(f"**Illustrator:** {safe_display(card.get('illustrator'))}")
                    st.markdown(f"**Rarity:** {safe_display(card.get('rarity'))}")
                    price = card.get('market_price')
                    st.markdown(f"**Market Price:** ${price:.2f}" if price else "**Market Price:** ⚠️ Missing")
                
                # Rapid confirm/reject buttons
                btn_col1, btn_col2 = st.columns(2)
                with btn_col1:
                    if st.button("✅ Confirm", key=f"conf_{card['card_id']}_{i}", use_container_width=True):
                        with engine.begin() as tx:
                            tx.execute(text("""
                                UPDATE tcg_cards 
                                SET art_style = :style, labeled_by = 'Human_Audit', updated_at = CURRENT_TIMESTAMP
                                WHERE card_id = :id
                            """), {"style": json.dumps([target]), "id": card['card_id']})
                        st.toast(f"Confirmed {card['name']}!")
                        # Remove from current view
                        st.session_state['tinder_candidates'].pop(i)
                        st.rerun()
                        
                with btn_col2:
                    if st.button("❌ Reject", key=f"rej_{card['card_id']}_{i}", use_container_width=True):
                        st.toast(f"Skipped {card['name']}.")
                        st.session_state['tinder_candidates'].pop(i)
                        st.rerun()