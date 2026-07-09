# src/dashboard/utils.py
import streamlit as st
import pandas as pd
import json
from sqlalchemy import text
import os

from src.database.connection import get_engine as get_base_engine

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))

# --- TAXONOMY TRI-TIER ARCHITECTURE ---

## --- TIER 1: Human Ground Truth (Manual / Distinct Styles) ---
CORE_STYLES = [
    "handcrafted_diorama",
    "textile_craft",
    "pen_and_ink_stippling",
    "soft_geometric_stencil",
    "canvas_paintings",
    "crisp_digital_portrait",
    "pixel_art",
    "retro_90s_anime"
]

# --- TIER 2: Zero-Touch Automation (Completely Handed to Model) ---
AUTO_STYLES = [
    "3d_cgi_render",
    "sketchbook_comic",       # Pencil/comic style drawings
    "heavy_pencil",          # Standard pencil illustrations
    "heavy_acrylic_oil",
    "chalk_pastel",
    "watercolor_and_ink"
]

# --- TIER 3: Dynamic Discovery Pool (Assisted / Open-Ended) ---
# These are known baseline remaining styles. The engine can also propose novel tags.
SUGGESTED_REMAINING_STYLES = [
    "stained_glass",
    "pop_art",
    "wood_block",
    "ukiyo_e",
    "standard_generic"
]

# Global validation array
ART_STYLE_KEYS = CORE_STYLES + AUTO_STYLES + SUGGESTED_REMAINING_STYLES

# --- AESTHETICS ---
AESTHETIC_KEYS = [
    "kinetic", "chaotic", "modern", "whimsical", "legendary", "neutral",
    "minimalist", "maximalist", "cinematic", "surrealist", "traditional_hand_painted",
    "eerie_gothic", "cottagecore", "lush_botanical", "neon_cyberpunk", "high_stakes_showdown"
]

# --- UI COMPONENTS ---
def render_sidebar():
    with st.sidebar:
        st.title("TCG Auditor")
        st.page_link("app.py", label="Home", icon="🏠")
        st.page_link("pages/1_Data_Ingestor.py", label="Data Ingestor", icon="📥")
        st.page_link("pages/2_Data_Healing.py", label="Data Healing", icon="🩹")
        st.page_link("pages/3_Human_Labelling.py", label="Human Labelling", icon="🕵️")
        st.page_link("pages/4_Vector_Tinder.py", label="Vector Tinder", icon="🎯")
        st.page_link("pages/5_Model_Metrics.py", label="Model Metrics", icon="📊")

# Wrap the base engine in the Streamlit cache
@st.cache_resource
def get_engine():
    """
    Streamlit-specific singleton wrapper for the database engine.
    Prevents Streamlit UI refreshes from exhausting the connection pool.
    """
    return get_base_engine()