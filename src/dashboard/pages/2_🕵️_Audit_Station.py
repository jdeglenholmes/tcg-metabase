import streamlit as st
import json
import requests
from io import BytesIO
from PIL import Image
from sqlalchemy import text
from google import genai
import os
from src.dashboard.utils import render_sidebar, get_engine, ART_STYLE_KEYS
from pydantic import BaseModel, Field

# 1. Define your strict schema
class AppraisalResult(BaseModel):
    style: str = Field(description="The exact name of the selected art style category.")
    reason: str = Field(description="A brief, 1-sentence justification explaining the medium or aesthetic.")


st.set_page_config(page_title="Audit Station", layout="wide")
render_sidebar()

st.title("🕵️ Human-in-the-Loop Audit Station")
st.markdown("Review unclassified cards, override KNN mistakes to teach the model, or escalate to the AI Critic.")

# --- 1. FETCH A CARD TO REVIEW ---
engine = get_engine()

# Fetch 1 card that needs review (either NULL, Manual Review, or you can change this to spot-check KNN)
query = text("""
    SELECT card_id, image_url, name, illustrator, art_style 
    FROM tcg_cards 
    WHERE REPLACE(supertype, 'é', 'e') = 'Pokemon' 
      AND (art_style IS NULL OR art_style = '"Manual review needed"')
      AND image_url IS NOT NULL
    LIMIT 1
""")

with engine.connect() as conn:
    card = conn.execute(query).mappings().fetchone()

if not card:
    st.success("🎉 INBOX ZERO! All cards have been classified.")
    st.stop()

# --- 2. DB UPDATE FUNCTION ---
def lock_in_style(selected_style, labeled_by):
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE tcg_cards 
            SET art_style = :style, labeled_by = :labeled_by
            WHERE card_id = :card_id
        """), {"style": json.dumps(selected_style), "labeled_by": labeled_by, "card_id": card['card_id']})
    st.rerun()

@st.fragment
def update_artist_widget(card_id, current_artist):
    # Create a small, self-contained mini-form
    st.write("---")
    st.caption("Fix Missing Metadata")
    
    # If the artist is 'Unknown', show a blank box. Otherwise, show current name.
    default_val = "" if current_artist == "Unknown" else current_artist
    
    new_artist = st.text_input("Illustrator Name:", value=default_val, key=f"input_{card_id}")
   

    if st.button("Save Artist", key=f"save_{card_id}"):
         # Enforce sentence case
        formatted_artist = new_artist.title()

        with engine.begin() as conn:
            conn.execute(text("""
                UPDATE tcg_cards 
                SET illustrator = :artist 
                WHERE card_id = :id
            """), {"artist": formatted_artist, "id": card_id})
            
        st.success(f"Updated Illustrator to: {formatted_artist}")

# --- 3. THE UI DECK ---
col1, col2 = st.columns([1, 2], gap="large")

with col1:
    st.image(card['image_url'], use_container_width=True)
    st.caption(f"** | Illus: {card['illustrator']}")

    # Inject the fragment here!
    update_artist_widget(card['card_id'], card['illustrator'])

with col2:
    st.subheader("Appraise Artwork")
    st.write("Select the correct style to lock it into the database. This updates the Gold Standard for the KNN.")
    
    # Render buttons for all available styles
    cols = st.columns(3)
    for i, style in enumerate(ART_STYLE_KEYS):
        if cols[i % 3].button(style.replace("_", " ").title(), use_container_width=True, key=style):
            lock_in_style(style, "Human_Audit")
            
    st.divider()
    
    # --- 4. THE AI CRITIC LIFELINE ---
    st.subheader("🤖 Not sure? Ask the AI Critic")
    
    # Initialize session state to hold the AI's answer
    if "ai_suggestion" not in st.session_state:
        st.session_state.ai_suggestion = None
        st.session_state.ai_reason = None

    # BUTTON 1: Fetch the data and save it to state
    if st.button("Escalate to Gemini Vision", type="primary", use_container_width=True):
        with st.spinner("Gemini is analyzing the brushstrokes..."):
            try:
                client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
                
                img_resp = requests.get(card['image_url'], headers={"User-Agent": "TCG/1.0"}, timeout=10)
                img = Image.open(BytesIO(img_resp.content)).convert('RGB')
                
                prompt = f"Classify this Pokemon card art into exactly ONE of these categories: {ART_STYLE_KEYS}"
                
                response = client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=[prompt, img],
                    config={
                        "temperature": 0.0,
                        "response_mime_type": "application/json",
                        "response_schema": AppraisalResult,
                    }
                )
                
                ai_decision = AppraisalResult.model_validate_json(response.text)
                
                if ai_decision.style in ART_STYLE_KEYS:
                    # Save to Streamlit memory instead of rendering a button directly!
                    st.session_state.ai_suggestion = ai_decision.style
                    st.session_state.ai_reason = ai_decision.reason
                    st.rerun() # Force a UI refresh to show the results
                else:
                    st.error(f"AI chose an invalid style: {ai_decision.style}")
                    
            except Exception as e:
                st.error(f"AI Critic failed: {e}")

    # RENDER SAVED STATE: If we have an AI suggestion in memory, display it
    if st.session_state.ai_suggestion:
        st.success(f"**AI Suggests:** {st.session_state.ai_suggestion}")
        st.info(f"**Reason:** {st.session_state.ai_reason}")
        
        # BUTTON 2: The Accept Button (Now independent of the first button!)
        if st.button(f"Accept AI Suggestion ({st.session_state.ai_suggestion})", type="primary", use_container_width=True):
            
            # 1. Grab the style to save
            style_to_save = st.session_state.ai_suggestion
            
            # 2. CLEAR the session state so the next card starts fresh!
            st.session_state.ai_suggestion = None
            st.session_state.ai_reason = None
            
            # 3. Save to database (this will trigger a rerun automatically)
            lock_in_style(style_to_save, "AI_Critic")