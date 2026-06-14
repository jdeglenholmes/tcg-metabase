# src/dashboard/pages/2_🔍_Card_Fetcher.py
import streamlit as st
import pandas as pd
import json
from sqlalchemy import text
from src.dashboard.utils import get_engine, ART_STYLE_KEYS, render_sidebar

st.set_page_config(page_title="...", layout="wide")
render_sidebar()

st.title("🔍 Card Fetcher & Human Review")
st.markdown("Audit KNN assignments, correct mislabeled styles, and flag suspicious cards.")

# --- THE EXPANDER FIX: Unique Search ID ---
if "search_id" not in st.session_state:
    st.session_state.search_id = 0
if "current_results" not in st.session_state:
    st.session_state.current_results = pd.DataFrame()

with st.sidebar:
    st.header("⚙️ Fetch Parameters")
    selected_set = st.text_input("Set ID (Blank for All)", placeholder="e.g., swsh1")
    
    # Notice we add the KNN ambiguous label to the top of the search so you can target them
    style_options = ["Any", "Manual review needed"] + ART_STYLE_KEYS
    selected_style = st.selectbox("🎨 Art Style", options=style_options)
    
    fetch_limit = st.slider("Cards to Fetch", 10, 100, 50)
    
    if st.button("🚀 Fetch Cards", type="primary", use_container_width=True):
        # Increment the search ID. This completely resets the expanders on the main page.
        st.session_state.search_id += 1 
        
        engine = get_engine()
        query_lines = ["SELECT * FROM tcg_cards WHERE REPLACE(supertype, 'é', 'e') = 'Pokemon'"]
        params = {"limit": fetch_limit}
        
        if selected_set:
            query_lines.append("AND set_id ILIKE :set_id")
            params["set_id"] = f"%{selected_set}%"
            
        if selected_style != "Any":
            if selected_style == "Manual review needed":
                query_lines.append("AND art_style = '\"Manual review needed\"'")
            else:
                query_lines.append("AND art_style = :style")
                params["style"] = json.dumps(selected_style)
                
        query_lines.append("LIMIT :limit")
        query = text(" ".join(query_lines))
        
        with engine.connect() as conn:
            st.session_state.current_results = pd.read_sql(query, conn, params=params)

# --- RENDER RESULTS ---
df = st.session_state.current_results

if df.empty:
    st.info("👈 Use the sidebar to fetch cards for review.")
else:
    st.success(f"Fetched {len(df)} cards for review.")
    
    # Create a nice grid layout
    cols = st.columns(4)
    for idx, row in df.iterrows():
        with cols[idx % 4]:
            st.image(row['image_url'], use_container_width=True)
            
            # THE FIX: By attaching search_id to the key, Streamlit treats it as a brand new widget every fetch
            expander_key = f"exp_{row['card_id']}_{st.session_state.search_id}"
            
            # The UI Expander
            with st.expander("📝 Metadata & Actions", expanded=False):
                st.caption(f"**Name:** {row['name']}")
                st.caption(f"**Illustrator:** {row['illustrator']}")
                
                try:
                    # Cleanly parse JSON tags
                    tags_dict = json.loads(row['tags']) if isinstance(row['tags'], str) else (row['tags'] or {})
                except:
                    tags_dict = {}
                
                # Show Flag Status
                is_flagged = tags_dict.get("flagged_suspicious", False)
                if is_flagged:
                    st.error("🚩 Flagged for AI Audit")
                
                # Action: Flag Button
                if not is_flagged:
                    if st.button("🚩 Flag Suspicious", key=f"flag_{expander_key}", use_container_width=True):
                        tags_dict["flagged_suspicious"] = True
                        engine = get_engine()
                        with engine.begin() as conn:
                            conn.execute(
                                text("UPDATE tcg_cards SET tags = :tags WHERE card_id = :card_id"),
                                {"tags": json.dumps(tags_dict), "card_id": row['card_id']}
                            )
                        # We do NOT increment search_id here, so the expander stays open after clicking!
                        st.session_state.current_results.at[idx, 'tags'] = json.dumps(tags_dict)
                        st.rerun()