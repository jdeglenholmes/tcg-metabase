# src/dashboard/app.py
import streamlit as st

st.set_page_config(page_title="TCG ML Studio", layout="wide", page_icon="🎴")

st.title("🎴 TCG ML Studio")
st.markdown("""
Welcome to the refined 3-module pipeline. Our current primary directive is achieving **100% database health** and **bulletproof `art_style` tagging** across all Pokémon cards.

### 🧭 Navigation (Use the Sidebar)
* **📥 1. Data Ingestor**: The automated ETL engine. Fetch API data, calculate CLIP embeddings, and execute initial KNN art style estimations.
* **🔍 2. Card Fetcher (Human Review)**: The manual verification hub. Audit the KNN assignments, correct errors, and flag suspicious cards.
* **📊 3. Command Center**: The intelligent mid-layer. Track database volume, model health, and receive automated directives on your next steps.
""")