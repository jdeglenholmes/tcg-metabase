# src/dashboard/pages/4_🧪_Model_Testing.py
import streamlit as st
import subprocess
import sys
from sqlalchemy import text
import pandas as pd
from src.dashboard.utils import render_sidebar, PROJECT_ROOT, get_engine
from src.dashboard.utils import ART_STYLE_KEYS, load_clip_model
import torch
import clip
import ast
import json

st.set_page_config(page_title="Model Testing", layout="wide", page_icon="🧪")
user_name, selected_set = render_sidebar()

st.title("🧪 Model Testing & AI Critic")
st.write("Train the Multi-Modal Neural Network on your tags, and use the AI Critic to hunt for human inconsistencies.")

st.markdown("### 1. Train Multi-Modal Neural Network")
if st.button("🚀 Train Custom Model", type="primary"):
    st.markdown("#### Live Training Logs:")
    with st.container(border=True):
        process = subprocess.Popen(
            [sys.executable, "-u", "-m", "src.ml.train_model"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=PROJECT_ROOT
        )
        log_box = st.empty()
        full_log = ""
        for line in iter(process.stdout.readline, ''):
            full_log += line
            log_box.code(full_log, language="bash")
        process.wait()
        
    if process.returncode == 0:
        st.success("🎯 Custom Neural Network trained and deployed successfully!")
    else:
        st.error("❌ Training failed. Check logs.")

st.markdown("---")

st.markdown("### 2. The AI Critic (QA Audit)")
if st.button("🕵️ Run AI Critic Audit"):
    st.markdown("#### Audit Logs:")
    with st.container(border=True):
        process = subprocess.Popen(
            [sys.executable, "-u", "-m", "src.ml.ai_critic"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=PROJECT_ROOT
        )
        log_box = st.empty()
        full_log = ""
        for line in iter(process.stdout.readline, ''):
            full_log += line
            log_box.code(full_log, language="bash")
        process.wait()

# --- KNN HOMEWORK CHECKER (AUDIT MODULE) ---
st.markdown("---")
st.header("🕵️‍♀️ Flagged Card Audit (Homework Checker)")
st.markdown("Use Zero-Shot CLIP to audit and correct cards you flagged as suspicious from the Card Fetcher.")

# Fetch only flagged cards
audit_query = text("""
    SELECT card_id, name, illustrator, image_url, tags, image_embedding 
    FROM tcg_cards 
    WHERE tags->>'flagged_suspicious' = 'true';
""")
engine = get_engine()
with engine.connect() as conn:
    audit_df = pd.read_sql(audit_query, conn)

if audit_df.empty:
    st.info("🎉 No cards are currently flagged for review!")
else:
    st.warning(f"🚨 {len(audit_df)} cards require an AI Audit.")
    
    if st.button("🧠 Run CLIP Zero-Shot Audit", type="primary"):
        with st.spinner("Loading Vision Model and grading KNN's homework..."):
            model, device = load_clip_model()
            text_inputs = clip.tokenize([f"A trading card illustration in the {style} style." for style in ART_STYLE_KEYS]).to(device)
            
            with torch.no_grad():
                text_features = model.encode_text(text_inputs)
                text_features /= text_features.norm(dim=-1, keepdim=True)
                
            cols = st.columns(3)
            for idx, row in audit_df.iterrows():
                with cols[idx % 3]:
                    with st.container(border=True):
                        st.image(row['image_url'], use_container_width=True)
                        st.markdown(f"**{row['name']}** by {row['illustrator']}")
                        
                        tags_dict = json.loads(row['tags']) if isinstance(row['tags'], str) else row['tags']
                        current_style = [k for k in ART_STYLE_KEYS if tags_dict.get(k) is True]
                        st.error(f"**Current Label:** {current_style[0] if current_style else 'None'}")
                        
                        # Run the image embedding against ALL Art Styles
                        img_emb = torch.tensor(ast.literal_eval(row['image_embedding']), dtype=torch.float32).to(device).unsqueeze(0)
                        similarities = (100.0 * img_emb @ text_features.T).softmax(dim=-1).squeeze().cpu().numpy()
                        
                        # Get Top 3 Predictions
                        top_indices = similarities.argsort()[-3:][::-1]
                        
                        st.markdown("**CLIP's Top 3 Corrections:**")
                        for i in top_indices:
                            predicted_style = ART_STYLE_KEYS[i]
                            confidence = similarities[i] * 100
                            
                            # If you click a correction, it overwrites the old style and removes the flag
                            if st.button(f"Accept: {predicted_style} ({confidence:.1f}%)", key=f"fix_{row['card_id']}_{predicted_style}"):
                                # Clean out old styles and the flag
                                for k in ART_STYLE_KEYS:
                                    tags_dict.pop(k, None)
                                tags_dict.pop("flagged_suspicious", None)
                                
                                # Assign new style
                                tags_dict[predicted_style] = True
                                
                                with engine.begin() as update_conn:
                                    update_conn.execute(
                                        text("UPDATE tcg_cards SET tags = :tags WHERE card_id = :card_id;"),
                                        {"tags": json.dumps(tags_dict), "card_id": row['card_id']}
                                    )
                                st.rerun()