# src/dashboard/pages/2_🏷️_Data_Labeler.py
import streamlit as st
from src.dashboard.utils import (
    render_sidebar, get_labeling_state, save_label_to_db, format_set_name,
    ART_STYLE_KEYS, AESTHETIC_KEYS, BINARY_FEATURES
)

st.set_page_config(page_title="Data Labeler", layout="wide", page_icon="🏷️")
user_name, selected_set = render_sidebar()

st.title(f"🏷️ Labeler: {format_set_name(selected_set)}")
db_df, user_history = get_labeling_state(selected_set, user_name)

if db_df.empty:
    st.warning("No cards found for this set. Try ingesting it first in the Data Ingestor.")
else:
    unlabeled_df = db_df[db_df['tags'].isnull()]
    
    if unlabeled_df.empty:
        st.success("🎉 You have completely labeled this set!")
        st.balloons()
    else:
        current_card = unlabeled_df.iloc[0]
        st.subheader(f"Labeling: {current_card['name']} ({current_card['card_id']})")
        
        col1, col2 = st.columns([1, 2])
        with col1:
            st.image(current_card['image_url'], use_container_width=True)
            st.caption(f"**Illustrator**: {current_card['illustrator']}")
            
        with col2:
            with st.form(key=f"label_form_{current_card['card_id']}"):
                selections = {}
                c1, c2, c3 = st.columns(3)
                with c1:
                    st.markdown("### Art Styles")
                    for style in ART_STYLE_KEYS:
                        selections[style] = st.checkbox(style.replace("_", " ").title())
                with c2:
                    st.markdown("### Aesthetics")
                    for aes in AESTHETIC_KEYS:
                        selections[aes] = st.checkbox(aes.replace("_", " ").title())
                with c3:
                    st.markdown("### Binary")
                    for bf in BINARY_FEATURES:
                        selections[bf] = st.checkbox(bf.replace("_", " ").title())
                        
                submit = st.form_submit_button("💾 Save & Next", type="primary", use_container_width=True)
                if submit:
                    save_label_to_db(current_card['card_id'], user_name, selections)
                    st.rerun()