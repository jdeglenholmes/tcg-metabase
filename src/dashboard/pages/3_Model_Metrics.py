import sys
import os

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

import streamlit as st
import pandas as pd
import json
from sqlalchemy import text
from src.dashboard.utils import render_sidebar, get_engine, ART_STYLE_KEYS

st.set_page_config(page_title="Model Metrics", layout="wide")
render_sidebar()

st.title("📊 Active Learning Metrics")
st.markdown("Track the health of the classification pipeline, human anchor distribution, and weekly velocity.")

engine = get_engine()

@st.cache_data(ttl=60)
def fetch_metrics():
    # Extracts the styles and flags if the card was updated in the last 7 days
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
        
    df['clean_style'] = df['art_style'].apply(
        lambda x: json.loads(x) if isinstance(x, str) and x.startswith('"') else x
    )
    return df

df = fetch_metrics()

if df.empty:
    st.warning("No labeled data found in the database.")
else:
    # Calculate Core Metrics
    total_cards = len(df)
    needs_review = len(df[df['clean_style'] == 'Manual review needed'])
    human_anchors = len(df[df['labeled_by'] == 'Human_Audit'])

    col1, col2, col3 = st.columns(3)
    col1.metric("Total Labeled/Reviewed", total_cards)
    col2.metric("Human Anchors Locked", human_anchors)
    col3.metric("Pending Review", needs_review)

    st.divider()

    st.subheader("Gravity by Art Style (Taxonomy Distribution)")
    
    # Calculate breakdown including 7-day velocity
    breakdown_data = []
    for style in ART_STYLE_KEYS:
        style_df = df[df['clean_style'] == style]
        human_count = len(style_df[style_df['labeled_by'] == 'Human_Audit'])
        auto_count = len(style_df[style_df['labeled_by'] != 'Human_Audit'])
        weekly_growth = style_df['recent_update'].sum()
        
        breakdown_data.append({
            "clean_style": style,
            "Human_Audit": human_count,
            "pipeline_auto": auto_count,
            "7_Day_Growth": f"+{weekly_growth}" if weekly_growth > 0 else "-"
        })
        
    style_breakdown = pd.DataFrame(breakdown_data).sort_values(by="Human_Audit", ascending=False)

    st.dataframe(
        style_breakdown,
        column_config={
            "clean_style": "Art Style Taxonomy",
            "Human_Audit": st.column_config.ProgressColumn(
                "Human Anchors (Gravity)",
                help="Higher numbers mean stronger pull for the KNN algorithm.",
                format="%f",
                min_value=0,
                max_value=int(max(style_breakdown['Human_Audit'].max(), 1)),
            ),
            "pipeline_auto": "Auto-Classified",
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
        st.warning(f"**Low Gravity Detected:** The following styles have fewer than 5 Human Anchors. The model will struggle to assign these until you lock in more examples:\n\n`{', '.join(weak_categories)}`")
    
    if 'pipeline_auto' in style_breakdown.columns:
        massive_categories = style_breakdown[style_breakdown['pipeline_auto'] > 2000]['clean_style'].tolist()
        if massive_categories:
            st.error(f"**Taxonomy Bottleneck:** The following categories are absorbing a massive amount of cards (`{', '.join(massive_categories)}`). The taxonomy here may not be specific enough. Consider breaking these down into sub-styles to capture more nuanced artwork.")