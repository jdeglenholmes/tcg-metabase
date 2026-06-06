import pandas as pd
import os
from sqlalchemy import text
from src.database.connection import get_engine

# The Golden Rules: If this artist drew the card, it MUST have this tag.
# You can expand this dictionary as you learn more about specific illustrators.
ARTIST_ANCHORS = {
    # The physical sculptors
    "Asako Ito": "handcrafted_diorama",
    "Yuka Morii": "handcrafted_diorama",
    
    # The 3D render studios
    "5ban Graphics": "crisp_digital_portrait",
    "PLANETA": "crisp_digital_portrait",
    "N-DESIGN Inc.": "crisp_digital_portrait",
    
    # The abstract/bizarre artists
    "Tomokazu Komiya": "surreal_abstract",
    "Shinji Kanda": "surreal_abstract",
    
    # The intense detail artists
    "AKIRA EGAWA": "maximalist",
    
    # The pure cartoon/doodle artists
    "Ooyama": "whimsical"
}

def run_artist_audit(csv_path="master_ground_truth.csv"):
    if not os.path.exists(csv_path):
        print(f"❌ Could not find {csv_path}.")
        return

    print("🔍 Starting Artist Anchor Audit...")
    df_labels = pd.read_csv(csv_path)
    
    # 1. Fetch artist data from PostgreSQL
    card_ids = tuple(df_labels['card_id'].tolist())
    engine = get_engine()
    
    query = f"""
        SELECT card_id, artist 
        FROM tcg_cards 
        WHERE card_id IN {card_ids};
    """
    with engine.connect() as conn:
        df_artists = pd.read_sql_query(text(query), conn)

    # 2. Merge labels with the artist data
    df_merged = pd.merge(df_labels, df_artists, on='card_id', how='left')
    
    audit_failures = []

    # 3. Perform the Audit
    for index, row in df_merged.iterrows():
        artist = str(row['artist'])
        
        # Check if the artist is in our Golden Dictionary
        # We use 'in artist' to catch variations like "Illus. Asako Ito"
        for anchor_name, required_tag in ARTIST_ANCHORS.items():
            if anchor_name in artist:
                
                # Check if the required tag is actually in our CSV columns
                if required_tag in row:
                    # If the tag is 0 (missing), we have a failure!
                    if row[required_tag] == 0:
                        audit_failures.append({
                            "card_id": row['card_id'],
                            "artist": artist,
                            "missing_required_tag": required_tag,
                            "note": f"Artist {anchor_name} is famous for {required_tag}. Please review this label."
                        })
                break # Move to next card once an anchor is found

    # 4. Report Results
    if not audit_failures:
        print("✅ Audit Passed! Your subjective labels perfectly match objective artist realities.")
    else:
        failure_df = pd.DataFrame(audit_failures)
        failure_df.to_csv("audit_failures.csv", index=False)
        print(f"⚠️ Audit Failed: Found {len(audit_failures)} inconsistencies.")
        print("📁 Review 'audit_failures.csv' to correct these in your master_ground_truth.csv file.")

if __name__ == "__main__":
    run_artist_audit()