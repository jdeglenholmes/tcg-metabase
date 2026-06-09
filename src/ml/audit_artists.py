import pandas as pd
import json
from sqlalchemy import text
from src.database.connection import get_engine

# The Golden Rules
ARTIST_ANCHORS = {
    "Asako Ito": "handcrafted_diorama",
    "Yuka Morii": "handcrafted_diorama",
    "5ban Graphics": "crisp_digital_portrait",
    "PLANETA": "crisp_digital_portrait",
    "N-DESIGN Inc.": "crisp_digital_portrait",
    "Tomokazu Komiya": "surrealist", # Updated to match your new taxonomy
    "Shinji Kanda": "surrealist",    # Updated to match your new taxonomy
    "AKIRA EGAWA": "maximalist",
    "Ooyama": "whimsical"
}

def run_artist_audit():
    print("🔍 Starting Artist Anchor Audit from Database...")
    engine = get_engine()
    
    # Fetch only human-tagged cards
    query = """
        SELECT card_id, name, illustrator, tags 
        FROM tcg_cards 
        WHERE tags IS NOT NULL;
    """
    
    with engine.connect() as conn:
        df = pd.read_sql(text(query), conn)

    if df.empty:
        print("❌ No tagged cards found in the database.")
        return

    audit_failures = []

    for _, row in df.iterrows():
        artist = str(row['illustrator']) # Using DB column name
        
        # Safely parse JSONB tags
        tags_dict = row.get('tags', {})
        if isinstance(tags_dict, str):
            try: tags_dict = json.loads(tags_dict)
            except: tags_dict = {}

        for anchor_name, required_tag in ARTIST_ANCHORS.items():
            if anchor_name in artist:
                # If the required tag is 0, missing, or False -> Failure!
                if not tags_dict.get(required_tag):
                    audit_failures.append({
                        "card_id": row['card_id'],
                        "card_name": row['name'],
                        "artist": artist,
                        "missing_required_tag": required_tag
                    })
                break 

    if not audit_failures:
        print("✅ Audit Passed! Your subjective labels perfectly match objective artist realities.")
    else:
        # Output failures so you can fix them in the Streamlit Labeler
        failure_df = pd.DataFrame(audit_failures)
        failure_df.to_csv("audit_failures.csv", index=False)
        print(f"⚠️ Audit Failed: Found {len(audit_failures)} inconsistencies.")
        print("📁 Review 'audit_failures.csv' and update them in your Streamlit app.")

if __name__ == "__main__":
    run_artist_audit()