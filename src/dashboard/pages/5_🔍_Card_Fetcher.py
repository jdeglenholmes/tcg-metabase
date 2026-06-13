# src/dashboard/pages/4_🔍_Card_Fetcher.py
import streamlit as st
import pandas as pd
import json
from sqlalchemy import text
from src.dashboard.utils import get_engine, ART_STYLE_KEYS, AESTHETIC_KEYS, render_sidebar

st.set_page_config(page_title="Card Fetcher", layout="wide", page_icon="🔍")
user_name, _ = render_sidebar()

st.title("🔍 Modular Card Fetcher")
st.markdown("Filter and fetch specific cross-sections of your database using your newly enriched AI tags and metadata.")

# --- 1. VARIABLE INPUTS (SIDEBAR) ---
with st.sidebar:
    st.header("⚙️ Fetch Parameters")
    
    # Set Filter (Default: blank/All Sets)
    selected_set = st.text_input("Set ID/Name", value="", placeholder="e.g., swsh1 (Leave blank for All)")
    
    # Art Style (Default: Any)
    selected_style = st.selectbox("🎨 Art Style", options=["Any"] + ART_STYLE_KEYS)
    
    # Aesthetic (Default: Any)
    selected_aesthetic = st.selectbox("✨ Card Aesthetic", options=["Any"] + AESTHETIC_KEYS)
    
    # Binary Features (Default: False)
    st.markdown("**Special Features:**")
    has_trainer = st.checkbox("Has Trainer (is_trainer_gallery)")
    has_cameo = st.checkbox("Cameo Card (has_cameo)")
    
    st.markdown("---")
    # Fetch Limit (Default: 20)
    fetch_limit = st.number_input("Number of cards to fetch", min_value=1, max_value=1000, value=20)
    
    fetch_btn = st.button("🚀 Fetch Cards", type="primary", use_container_width=True)

# --- 2. DYNAMIC SQL EXECUTION & STATE MANAGEMENT ---
if "fetch_results" not in st.session_state:
    st.session_state.fetch_results = None

if fetch_btn:
    engine = get_engine()
    
    query_lines = [
        "SELECT card_id, name, set_id, illustrator, image_url, tags",
        "FROM tcg_cards",
        "WHERE supertype = 'Pokemon' AND image_url IS NOT NULL"
    ]
    params = {"limit": fetch_limit}
    
    if selected_set.strip():
        query_lines.append("AND set_id ILIKE :set_id")
        params["set_id"] = f"%{selected_set.strip()}%"
    if selected_style != "Any":
        query_lines.append("AND tags->>:style = 'true'")
        params["style"] = selected_style
    if selected_aesthetic != "Any":
        query_lines.append("AND tags->>:aesthetic = 'true'")
        params["aesthetic"] = selected_aesthetic
    if has_trainer:
        query_lines.append("AND tags->>'is_trainer_gallery' = 'true'")
    if has_cameo:
        query_lines.append("AND tags->>'has_cameo' = 'true'")
        
    query_lines.append("ORDER BY RANDOM() LIMIT :limit;") 
    
    with st.spinner("Executing database fetch..."):
        with engine.connect() as conn:
            st.session_state.fetch_results = pd.read_sql(text("\n".join(query_lines)), conn, params=params)

# --- 3. RENDER RESULTS & METADATA ---
if st.session_state.fetch_results is not None:
    df = st.session_state.fetch_results
    
    if df.empty:
        st.warning("No cards found matching those exact criteria. Try broadening your search!")
    else:
        st.success(f"✅ Displaying {len(df)} cards.")
        st.markdown("---")
        
        cols = st.columns(4)
        for idx, row in df.iterrows():
            with cols[idx % 4]:
                st.image(row['image_url'], use_container_width=True)
                st.markdown(f"**{row['name']}**")
                st.caption(f"🎨 {row['illustrator']} | 📦 {row['set_id'].upper()}")
                
                with st.expander("📊 Metadata & Actions"):
                    try:
                        tags_dict = json.loads(row['tags']) if isinstance(row['tags'], str) else (row['tags'] or {})
                        
                        # Categorize the active tags
                        active_styles = [k for k in ART_STYLE_KEYS if tags_dict.get(k) is True]
                        active_aesthetics = [k for k in AESTHETIC_KEYS if tags_dict.get(k) is True]
                        active_features = [k for k in ["has_cameo", "is_trainer_gallery"] if tags_dict.get(k) is True]
                        
                        st.markdown(f"**Art Style:** {', '.join(active_styles) if active_styles else 'None'}")
                        st.markdown(f"**Aesthetics:** {', '.join(active_aesthetics) if active_aesthetics else 'None'}")
                        st.markdown(f"**Features:** {', '.join(active_features) if active_features else 'None'}")
                        
                        st.divider()
                        
                        # The Flagging Mechanism
                        if tags_dict.get("flagged_suspicious"):
                            st.error("🚩 Flagged for AI Audit")
                        else:
                            if st.button("🚩 Flag as Suspicious", key=f"flag_{row['card_id']}", use_container_width=True):
                                tags_dict["flagged_suspicious"] = True
                                engine = get_engine()
                                with engine.begin() as conn:
                                    conn.execute(
                                        text("UPDATE tcg_cards SET tags = :tags WHERE card_id = :card_id;"),
                                        {"tags": json.dumps(tags_dict), "card_id": row['card_id']}
                                    )
                                st.rerun() # Refresh to show the red flagged state
                                
                    except Exception as e:
                        st.write("*Error parsing metadata.*")
                st.write("")