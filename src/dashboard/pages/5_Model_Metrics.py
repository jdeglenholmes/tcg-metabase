import sys
import os

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

import streamlit as st
import pandas as pd
import json
from sqlalchemy import text
from src.dashboard.utils import render_sidebar, get_engine

st.set_page_config(page_title="Model Metrics", layout="wide")
render_sidebar()

st.title("📊 Active Learning Metrics")
st.markdown("Track the health of the classification pipeline, human anchor distribution, and weekly velocity.")

engine = get_engine()

@st.cache_data(ttl=60)
def fetch_metrics():
    query = text("""
        SELECT 
            art_style, 
            labeled_by,
            CASE WHEN updated_at >= NOW() - INTERVAL '7 days' THEN 1 ELSE 0 END as recent_update
        FROM tcg_cards
        WHERE REPLACE(supertype, 'é', 'e') = 'Pokemon'
          AND art_style IS NOT NULL;
    """)
    with engine.connect() as conn:
        df = pd.read_sql(query, conn)
        
    # --- ROBUST JSON PARSER FOR PANDAS ---
    def parse_style(val):
        if pd.isna(val): return None
        if isinstance(val, list): return val[0] if len(val) > 0 else None
        if isinstance(val, str):
            try:
                parsed = json.loads(val)
                if isinstance(parsed, list) and len(parsed) > 0:
                    return parsed[0]
                if isinstance(parsed, str):
                    return parsed
            except Exception:
                pass
        return val

    df['clean_style'] = df['art_style'].apply(parse_style)
    
    # Mathematical Grouping
    style_breakdown = df.groupby(['clean_style', 'labeled_by']).size().unstack(fill_value=0).reset_index()
    
    # Ensure columns exist to prevent Streamlit UI crashes if a queue is empty
    for col in ['Human_Audit', 'Model_Auto', 'Model_Ambiguous']:
        if col not in style_breakdown.columns:
            style_breakdown[col] = 0
            
    # Calculate 7-day velocity
    velocity = df[df['recent_update'] == 1].groupby('clean_style').size().reset_index(name='7_Day_Growth')
    style_breakdown = pd.merge(style_breakdown, velocity, on='clean_style', how='left').fillna({'7_Day_Growth': 0})
    
    return style_breakdown

style_breakdown = fetch_metrics()

# --- Display Data ---
st.dataframe(
    style_breakdown,
    column_config={
        "clean_style": "Art Style",
        "Human_Audit": st.column_config.ProgressColumn(
            "Human Anchors (Gravity)",
            help="Higher numbers mean stronger pull for the discovery algorithm.",
            format="%f",
            min_value=0,
            max_value=int(max(style_breakdown['Human_Audit'].max(), 1)),
        ),
        "Model_Auto": "Auto-Classified",
        "Model_Ambiguous": "Pending Discovery",
        "7_Day_Growth": "7-Day Velocity"
    },
    hide_index=True,
    use_container_width=True
)

st.divider()

# Taxonomy Expansion Recommendations
st.subheader("💡 Taxonomy Recommendations")
st.markdown("Based on current active learning data, these areas require attention:")

weak_categories = style_breakdown[style_breakdown['Human_Audit'] < 5]['clean_style'].tolist()

if weak_categories:
    st.warning(f"**Low Gravity Detected:** The following styles have fewer than 5 Human Anchors. The Vector Tinder engine will struggle to surface candidates until you lock in more examples:\n\n`{', '.join(weak_categories)}`")

if 'Model_Auto' in style_breakdown.columns:
    massive_categories = style_breakdown[style_breakdown['Model_Auto'] > 2000]['clean_style'].tolist()
    if massive_categories:
        st.error(f"**Taxonomy Bottleneck:** The following categories are absorbing a massive amount of cards (`{', '.join(massive_categories)}`). You may need to split these into sub-styles.")