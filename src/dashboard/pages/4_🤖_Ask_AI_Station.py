import streamlit as st
import json
import ast
import pandas as pd
import numpy as np
from sklearn.neighbors import KNeighborsClassifier
from sqlalchemy import text
from src.dashboard.utils import render_sidebar, get_engine, ART_STYLE_KEYS
# --- ADD THESE TO YOUR IMPORTS ---
import os
import requests
from io import BytesIO
from PIL import Image
from pydantic import BaseModel, Field
from google import genai
# ---------------------------------

# Add your strict schema near the top of the file
class AppraisalResult(BaseModel):
    style: str = Field(description="The exact name of the selected art style category.")
    reason: str = Field(description="A brief, 1-sentence justification explaining the medium or aesthetic.")

st.set_page_config(page_title="Ask AI Station", layout="wide")
render_sidebar()

st.title("🤖 Ask AI Consultation Station")
st.markdown("Search for specific cards and get a live probability breakdown from the distance-weighted KNN model.")

engine = get_engine()

# -------------------------------------------------------------------------
# INTERACTIVE AI BRAIN (LIVE INFERENCE FUNCTION)
# -------------------------------------------------------------------------
def get_live_ai_opinion(target_embedding):
    """Trains a live mini-KNN instance on current data to return probabilities."""
    if not target_embedding:
        return None, "Error: Missing card image embedding."
        
    # 1. Pull current gold standard training pool
    train_query = text("""
        SELECT art_style, image_embedding, labeled_by 
        FROM tcg_cards 
        WHERE REPLACE(supertype, 'é', 'e') = 'Pokemon' 
          AND art_style IS NOT NULL 
          AND art_style != '"Manual review needed"'
          AND image_embedding IS NOT NULL;
    """)
    
    with engine.connect() as conn:
        train_df = pd.read_sql(train_query, conn)
        
    if train_df.empty:
        return None, "No training data available to generate an opinion."

    # 2. Parse embeddings and strip JSON quotes
    train_df['X'] = train_df['image_embedding'].apply(
        lambda x: ast.literal_eval(x) if isinstance(x, str) else x
    )
    train_df['y'] = train_df['art_style'].apply(
        lambda x: json.loads(x) if (isinstance(x, str) and x.startswith('"')) else x
    )

    # 3. Apply your 5x Human Anchor Gravity Multiplier
    human_anchors = train_df[train_df['labeled_by'] == 'Human_Audit']
    if not human_anchors.empty:
        train_df = pd.concat([train_df] + [human_anchors] * 4, ignore_index=True)

    X_train = np.array(train_df['X'].tolist())
    y_train = train_df['y'].values

    # 4. Fit the distance-weighted model
    knn = KNeighborsClassifier(n_neighbors=5, weights='distance')
    knn.fit(X_train, y_train)

    # 5. Predict probabilities for this single card
    target_vector = np.array([ast.literal_eval(target_embedding) if isinstance(target_embedding, str) else target_embedding])
    probabilities = knn.predict_proba(target_vector)[0]
    
    # Pair classes with their calculated probabilities and sort descending
    opinion_results = sorted(
        zip(knn.classes_, probabilities), 
        key=lambda x: x[1], 
        reverse=True
    )
    return opinion_results, None


# -------------------------------------------------------------------------
# UI STEP 1: SEARCH CONTROLS
# -------------------------------------------------------------------------
with st.container(border=True):
    st.subheader("🔍 Find Your Target Card")
    search_mode = st.radio("Search Strategy:", ["By Pokémon Name", "By Card ID & Set ID"], horizontal=True)
    
    cards = []
    
    if search_mode == "By Pokémon Name":
        search_name = st.text_input("Enter Pokémon Name (e.g., Machamp):", placeholder="Gengar")
        if search_name:
            query = text("""
                SELECT card_id, set_id, name, illustrator, image_url, art_style, image_embedding, labeled_by
                FROM tcg_cards
                WHERE REPLACE(supertype, 'é', 'e') = 'Pokemon'
                  AND name ILIKE :name
                LIMIT 20;
            """)
            with engine.connect() as conn:
                cards = conn.execute(query, {"name": f"%{search_name}%"}).mappings().fetchall()
                
    else:
        col1, col2 = st.columns(2)
        with col1:
            search_id = st.text_input("Card ID (e.g., base1-8):")
        with col2:
            search_set = st.text_input("Set ID (e.g., base1):")
            
        if search_id and search_set:
            query = text("""
                SELECT card_id, set_id, name, illustrator, image_url, art_style, image_embedding, labeled_by
                FROM tcg_cards
                WHERE REPLACE(supertype, 'é', 'e') = 'Pokemon'
                  AND card_id = :card_id
                  AND set_id ILIKE :set_id;
            """)
            with engine.connect() as conn:
                cards = conn.execute(query, {"card_id": search_id, "set_id": search_set}).mappings().fetchall()

# -------------------------------------------------------------------------
# UI STEP 2: RENDER MATCHES & ASK AI TRIGGER
# -------------------------------------------------------------------------
if search_mode == "By Pokémon Name" and search_name and not cards:
    st.warning(f"No Pokémon found matching '{search_name}'.")
elif search_mode == "By Card ID & Set ID" and search_id and search_set and not cards:
    st.warning("No exact card matched that ID and Set combination.")

if cards:
    st.divider()
    st.subheader(f"✨ Found {len(cards)} matching cards:")
    
    for card in cards:
        # Create a clean row wrapper for each card match
        with st.container(border=True):
            img_col, info_col, ai_col = st.columns([1, 2, 2])
            
            with img_col:
                if card['image_url']:
                    st.image(card['image_url'], use_container_width=True)
                else:
                    st.error("No Image Available")
                    
            with info_col:
                st.markdown(f"### {card['name']}")
                st.markdown(f"**ID:** `{card['card_id']}` | **Set:** `{card['set_id']}`")
                st.markdown(f"Artist:")
                
                # Render current classification
                try:
                    current_style = json.loads(card['art_style']) if card['art_style'] else "Unlabeled"
                except Exception:
                    current_style = card['art_style']
                
                st.markdown(f"**Current Label:** `{current_style}`")
                if card['labeled_by']:
                    st.caption(f"Source: *{card['labeled_by']}*")
                
                # Quick Override Selector
                st.divider()
                try:
                    clean_style = json.loads(card['art_style']) if card['art_style'] else None
                except Exception:
                    clean_style = card['art_style']
                    
                idx = ART_STYLE_KEYS.index(clean_style) if clean_style in ART_STYLE_KEYS else 0
                
                chosen_override = st.selectbox(
                    "Manually Correct Style:",
                    options=ART_STYLE_KEYS,
                    index=idx,
                    key=f"override_sel_{card['card_id']}"
                )
                
                if st.button("Lock As Human Anchor", key=f"lock_{card['card_id']}", type="secondary"):
                    with engine.begin() as conn:
                        conn.execute(text("""
                            UPDATE tcg_cards 
                            SET art_style = :style, labeled_by = 'Human_Audit'
                            WHERE card_id = :id
                        """), {"style": json.dumps(chosen_override), "id": card['card_id']})
                    st.success("Locked as a high-gravity Human Anchor!")
                    st.rerun()

            # --- REPLACE THE ENTIRE ai_col BLOCK WITH THIS ---
            with ai_col:
                st.markdown("#### 🧠 Gemini Vision Critic")
                
                if st.button("🔮 Ask Gemini for Opinion", key=f"gemini_btn_{card['card_id']}", type="primary", use_container_width=True):
                    with st.spinner("Gemini is analyzing the artwork..."):
                        try:
                            # Initialize the Gemini Client
                            client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
                            
                            # Fetch the image into memory
                            img_resp = requests.get(card['image_url'], headers={"User-Agent": "TCG/1.0"}, timeout=10)
                            img = Image.open(BytesIO(img_resp.content)).convert('RGB')
                            
                            prompt = f"Classify this Pokemon card art into exactly ONE of these categories: {ART_STYLE_KEYS}"
                            
                            # Call the 2.5 Flash model
                            response = client.models.generate_content(
                                model='gemini-2.5-flash',
                                contents=[prompt, img],
                                config={
                                    "temperature": 0.0,
                                    "response_mime_type": "application/json",
                                    "response_schema": AppraisalResult,
                                }
                            )
                            
                            # Parse the strict output
                            ai_decision = AppraisalResult.model_validate_json(response.text)
                            
                            # Display the results
                            if ai_decision.style in ART_STYLE_KEYS:
                                st.success(f"**Gemini Suggests:** {ai_decision.style}")
                                st.info(f"**Reason:** {ai_decision.reason}")
                            else:
                                st.error(f"Gemini chose an invalid style: {ai_decision.style}")
                                
                        except Exception as e:
                            st.error(f"Gemini API failed: {e}")