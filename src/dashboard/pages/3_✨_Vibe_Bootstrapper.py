# src/dashboard/pages/3_✨_Vibe_Bootstrapper.py
import streamlit as st
import torch
import clip
import pandas as pd
import json
import ast
from sqlalchemy import text
from src.dashboard.utils import render_sidebar, load_clip_model, get_engine, ALL_KEYS

st.set_page_config(page_title="Vibe Bootstrapper", layout="wide", page_icon="✨")
user_name, selected_set = render_sidebar()

st.title("✨ Zero-Shot Vibe Bootstrapper")
st.markdown("Search your entire database using natural language and review high-resolution matches before injecting them as training data.")

if "bootstrap_results" not in st.session_state:
    st.session_state.bootstrap_results = None
    st.session_state.target_tag = None

# --- 1. TOP CONTROL BAR ---
with st.container(border=True):
    col1, col2, col3, col4 = st.columns([3, 2, 1, 1])
    with col1: text_prompt = st.text_input("Visual Prompt", placeholder="e.g., 'A flat, ink-and-wash Japanese style...'")
    with col2: target_tag = st.selectbox("Assign to Database Tag:", options=ALL_KEYS)
    with col3: top_n = st.number_input("Cards to Retrieve", min_value=10, max_value=500, value=50)
    with col4: 
        st.write(""); st.write("")
        analyze_btn = st.button("🔍 Analyze", use_container_width=True)

# --- 2. THE PROMPT HISTORY EXPANDER ---
with st.expander("📜 View Prompt Run History", expanded=False):
    engine = get_engine()
    with engine.connect() as conn:
        history_df = pd.read_sql(text("SELECT created_at, created_by, prompt_text, target_tag, cards_affected, avg_confidence FROM bootstrap_history ORDER BY created_at DESC LIMIT 10;"), conn)
        if not history_df.empty:
            st.dataframe(history_df, use_container_width=True, hide_index=True)
        else:
            st.caption("No bootstrapped runs recorded yet.")

# --- 3. EXECUTION LOGIC ---
if analyze_btn and text_prompt:
    with st.spinner("Loading Vision Model and querying database..."):
        model, device = load_clip_model()
        
        # We added 'illustrator' to the SELECT statement
        query = """
            SELECT card_id, name, illustrator, tags, image_embedding, image_url 
            FROM tcg_cards 
            WHERE image_embedding IS NOT NULL 
            AND supertype = 'Pokemon';
        """
        
        with engine.connect() as conn:
            df = pd.read_sql(text(query), conn)

        if not df.empty:
            df['image_embedding'] = df['image_embedding'].apply(ast.literal_eval)
            image_features = torch.tensor(df['image_embedding'].tolist(), dtype=torch.float32).to(device)
            text_input = clip.tokenize([text_prompt]).to(device)
            
            with torch.no_grad():
                text_features = model.encode_text(text_input)
                text_features /= text_features.norm(dim=-1, keepdim=True)
                similarities = (image_features @ text_features.T).squeeze(1)
            
            df['similarity_score'] = similarities.cpu().numpy()
            st.session_state.bootstrap_results = df.sort_values(by='similarity_score', ascending=False).head(top_n)
            st.session_state.target_tag = target_tag

# --- 4. HIGH-RES VISUAL REVIEW & INDIVIDUAL TOGGLES ---
if st.session_state.bootstrap_results is not None:
    from src.dashboard.utils import ARTIST_ANCHORS  # Import the newly updated dictionary
    
    st.markdown("---")
    st.markdown(f"### Reviewing top {len(st.session_state.bootstrap_results)} matches for: **`{st.session_state.target_tag}`**")
    st.info("💡 **Tip:** All cards are selected by default. Cards highlighted in green perfectly match known Artist Anchors.")
    
    cols = st.columns(4)
    for idx, row in st.session_state.bootstrap_results.reset_index().iterrows():
        with cols[idx % 4]:
            st.image(row['image_url'], use_container_width=True)
            
            # Check if this card's artist is an anchor for the currently searched tag
            card_artist = str(row.get('illustrator', '')).lower()
            is_anchor_match = False
            
            for anchor_name, anchor_tag in ARTIST_ANCHORS.items():
                if anchor_name.lower() in card_artist and st.session_state.target_tag == anchor_tag:
                    is_anchor_match = True
                    break
            
            # Display special UI if it matches
            if is_anchor_match:
                st.success(f"**{row['name']}** (Conf: {row['similarity_score']:.2f})\n\n⭐️ **Anchor Match: {row['illustrator']}**")
            else:
                st.caption(f"**{row['name']}** (Conf: {row['similarity_score']:.2f}) | {row['illustrator']}")
                
            st.checkbox("Keep?", value=True, key=f"keep_{row['card_id']}")
            st.write("") # Padding

    st.markdown("---")
    
    # --- 5. SELECTIVE INJECTION & HISTORY LOGGING ---
    with st.container(border=True):
        st.warning(f"Ready to commit? Only checked cards will receive the '{st.session_state.target_tag}' tag.")
        if st.button("💾 Confirm & Inject Selected Labels", type="primary", use_container_width=True):
            cards_affected = 0
            kept_scores = []
            
            with st.spinner("Updating database..."):
                with engine.begin() as conn:
                    for _, row in st.session_state.bootstrap_results.iterrows():
                        if st.session_state.get(f"keep_{row['card_id']}", False):
                            current_tags = row['tags'] if row['tags'] else {}
                            if isinstance(current_tags, str): 
                                current_tags = json.loads(current_tags)
                                
                            current_tags[st.session_state.target_tag] = True
                            
                            update_query = text("UPDATE tcg_cards SET tags = :tags, updated_at = CURRENT_TIMESTAMP WHERE card_id = :card_id;")
                            conn.execute(update_query, {"tags": json.dumps(current_tags), "card_id": row['card_id']})
                            
                            cards_affected += 1
                            kept_scores.append(row['similarity_score'])
                    
                    avg_confidence = sum(kept_scores) / len(kept_scores) if kept_scores else 0.0
                    
                    log_query = text("""
                        INSERT INTO bootstrap_history (prompt_text, target_tag, cards_affected, avg_confidence, created_by)
                        VALUES (:prompt, :tag, :count, :avg_conf, :user);
                    """)
                    conn.execute(log_query, {
                        "prompt": text_prompt,
                        "tag": st.session_state.target_tag,
                        "count": cards_affected,
                        "avg_conf": float(avg_confidence),
                        "user": user_name
                    })
                            
            st.success(f"✅ Successfully injected {cards_affected} labels into the database!")
            st.session_state.bootstrap_results = None
            st.rerun()