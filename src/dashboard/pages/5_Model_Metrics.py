import sys
import os
import pandas as pd
import streamlit as st
from sqlalchemy import text

# Setup paths
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from src.dashboard.utils import render_sidebar, get_engine, ART_STYLE_KEYS

st.set_page_config(page_title="Model Metrics", layout="wide")
render_sidebar()

st.title("📊 Model Metrics & Ground Truth")
st.markdown("Track the strict, human-verified baseline required for supervised classifier training.")

engine = get_engine()

# --- 1. DATA FETCHING ---
@st.cache_data(ttl=60)
def fetch_metrics():
    # Progress & Baseline
    progress_query = text("""
        SELECT 
            COUNT(*) as total_cards,
            COUNT(*) FILTER (WHERE labeled_by = 'Human_Audit') as audited_cards
        FROM tcg_cards
        WHERE REPLACE(supertype, 'é', 'e') = 'Pokemon'
    """)
    
    # 24-Hour Velocity
    velocity_query = text("""
        SELECT 
            art_style::text as "Art Style",
            COUNT(*) as "24h Growth"
        FROM tcg_cards
        WHERE labeled_by = 'Human_Audit' 
          AND updated_at >= NOW() - INTERVAL '1 day'
          AND REPLACE(supertype, 'é', 'e') = 'Pokemon'
        GROUP BY art_style::text
        ORDER BY "24h Growth" DESC
    """)
    
    # Ground Truth Distribution (For ML Readiness)
    distribution_query = text("""
        SELECT 
            art_style::text as "Art Style",
            COUNT(*) as "Total Anchors"
        FROM tcg_cards
        WHERE labeled_by = 'Human_Audit'
          AND REPLACE(supertype, 'é', 'e') = 'Pokemon'
        GROUP BY art_style::text
        ORDER BY "Total Anchors" DESC
    """)
    
    with engine.connect() as conn:
        progress = conn.execute(progress_query).mappings().fetchone()
        velocity_df = pd.read_sql(velocity_query, conn)
        distribution_df = pd.read_sql(distribution_query, conn)
        
    return progress, velocity_df, distribution_df

progress, velocity_df, distribution_df = fetch_metrics()

# --- 2. TOP LEVEL KPIs ---
st.subheader("Target: 50+ Anchors per Core Style")
col1, col2, col3 = st.columns(3)

total = progress['total_cards'] or 0
audited = progress['audited_cards'] or 0
pending = total - audited
completion_pct = (audited / total * 100) if total > 0 else 0

col1.metric("Verified Ground Truth", f"{audited:,}")
col2.metric("Pending Discovery", f"{pending:,}")
col3.metric("Baseline Completion", f"{completion_pct:.2f}%")

st.divider()

# --- 3. VISUALIZATIONS ---
col_left, col_right = st.columns(2)

with col_left:
    st.subheader("🚀 24-Hour Labelling Velocity")
    st.markdown("Measures active human auditing output over the last day.")
    if not velocity_df.empty:
        # Clean up JSON formatting for the UI
        velocity_df['Art Style'] = velocity_df['Art Style'].str.strip('[]"')
        st.dataframe(velocity_df, use_container_width=True, hide_index=True)
    else:
        st.info("No manual labels recorded in the last 24 hours.")

with col_right:
    st.subheader("⚖️ ML Training Readiness")
    st.markdown("Current anchor count per style. (Aiming for ~50 to train the classifier)")
    if not distribution_df.empty:
        # Clean up JSON formatting for the UI
        distribution_df['Art Style'] = distribution_df['Art Style'].str.strip('[]"')
        st.bar_chart(distribution_df.set_index("Art Style"))
    else:
        st.info("No ground truth labels established yet.")