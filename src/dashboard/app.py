# src/dashboard/app.py
import streamlit as st

st.set_page_config(page_title="TCG ML Studio", layout="wide", page_icon="🎴")

st.title("🎴 Welcome to the TCG ML Studio")
st.markdown("""
This platform is organized into four distinct modules. **Use the sidebar on the left to navigate between pages.**

* **📥 Data Ingestor**: Manage raw API data, fetch bulk Pokémon sets, and generate 512-D visual embeddings.
* **🏷️ Data Labeler**: The manual verification hub. Review cards and manually tag their precise aesthetics and styles.
* **✨ Vibe Bootstrapper**: Search your database using natural language to rapidly auto-label complex visual themes.
* **🧪 Model Testing**: Train the multi-modal neural network and run the AI Critic to audit human inconsistencies.
""")