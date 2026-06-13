# inject_and_validate.py
import pandas as pd
import json
import sys
from sqlalchemy import text
from src.database.connection import get_engine  # Adjust import to match your database utility
from src.dashboard.utils import ART_STYLE_KEYS   # Your list of valid art styles

def run_sanity_checks(df):
    print("🔍 Step 1: Running Sanity Checks on 'new_output_enriched.csv'...")
    errors = 0

    # Check 1: Verify all art styles match the allowed taxonomy
    allowed_styles = set(ART_STYLE_KEYS) | {"Manual review needed"}
    unique_styles = df[df['supertype'].str.lower() == 'pokemon']['art_style'].dropna().unique()
    
    invalid_styles = [s for s in unique_styles if s not in allowed_styles]
    if invalid_styles:
        print(f"❌ ERROR: Found unauthorized art styles in CSV: {invalid_styles}")
        errors += 1
    else:
        print("✅ Taxonomy Check Passed: All labels match your ART_STYLE_KEYS.")

    # Check 2: Confirm JSON integrity in the 'tags' column
    json_corrupted = 0
    for idx, row in df.iterrows():
        if pd.notna(row['tags']):
            try:
                json.loads(row['tags'])
            except (json.JSONDecodeError, TypeError):
                json_corrupted += 1
                
    if json_corrupted > 0:
        print(f"❌ ERROR: Found {json_corrupted} rows with malformed JSON strings in the 'tags' column.")
        errors += 1
    else:
        print("✅ JSON Integrity Check Passed: All tags are structurally valid.")

    # Check 3: Ensure non-Pokemon cards were completely untouched
    non_pokemon_altered = df[(df['supertype'].str.lower() != 'pokemon') & (df['art_style'].notna())]
    if len(non_pokemon_altered) > 0:
        print(f"❌ ERROR: {len(non_pokemon_altered)} Trainer/Energy cards accidentally received an art style!")
        errors += 1
    else:
        print("✅ Supertype Check Passed: Non-Pokémon cards are safely untouched.")

    if errors > 0:
        print("\n🛑 Database injection aborted. Please fix the errors highlighted above.")
        sys.exit(1)
    else:
        print("\n🎉 All sanity checks passed! Proceeding to database injection...")

def inject_to_database(df):
    print("\n🚀 Step 2: Injecting labels into the database...")
    engine = get_engine()
    
    pokemon_updates = df[df['supertype'].str.lower() == 'pokemon']
    total_records = len(pokemon_updates)
    
    update_query = text("""
        UPDATE tcg_cards 
        SET art_style = :art_style,
            tags = :tags,
            updated_at = CURRENT_TIMESTAMP
        WHERE card_id = :card_id;
    """)

    with engine.begin() as conn:
        counter = 0
        for _, row in pokemon_updates.iterrows():
            # Extract raw values
            style_val = row['art_style'] if pd.notna(row['art_style']) else None
            tags_val = row['tags'] if pd.notna(row['tags']) else None
            
            # FIX: If art_style is a JSON column, string literals must be valid JSON string tokens
            if style_val is not None:
                style_val = json.dumps(style_val)  # Converts '3d_cgi_render' into '"3d_cgi_render"'
            
            conn.execute(update_query, {
                "art_style": style_val,
                "tags": tags_val,
                "card_id": row['card_id']
            })
            
            counter += 1
            if counter % 1000 == 0 or counter == total_records:
                print(f"  • Progress: {counter}/{total_records} cards synced...")

    print(f"\n✅ Success! Successfully synced {counter} records into the database.")

if __name__ == "__main__":
    try:
        enriched_df = pd.read_csv('new_output_enriched.csv')
        run_sanity_checks(enriched_df)
        inject_to_database(enriched_df)
    except FileNotFoundError:
        print("❌ Error: 'new_output_enriched.csv' not found. Run your enrichment script first.")