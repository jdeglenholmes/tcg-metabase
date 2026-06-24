import streamlit as st
from src.dashboard.utils import render_sidebar

st.set_page_config(page_title="TCG Labeler", layout="wide")
render_sidebar()

st.title("TCG Active Learning Command Center")
st.markdown("""
Welcome to the cloud-hosted auditing station. 

**Available Modules:**
* **🕵️ Human Labelling:** Swipe through unconfident predictions and lock in Human Anchors.
* **🤖 Ask AI Labelling:** Consult the Gemini Vision model for a second opinion on highly nuanced or ambiguous art styles.
* **📊 Label Metrics Dashboard:** Track active learning performance, cluster gravity, and identify areas where the taxonomy may need expansion.
""")