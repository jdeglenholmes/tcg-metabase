import sys
import os
import json
from sqlalchemy import text

# Ensure project root is in path
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from src.database.connection import get_engine

def restore_specific_anchors(backup_file_path):
    # The strict whitelist of styles you want to rescue
    TARGET_STYLES = ["retro_90s_anime"]
    
    print(f"📂 Loading backup file from: {backup_file_path}")
    try:
        with open(backup_file_path, 'r', encoding='utf-8') as f:
            backup_data = json.load(f)
    except FileNotFoundError:
        print("❌ Backup JSON not found. Please ensure it is in the root directory.")
        return

    # Filter for your pristine human audits of the target styles
    cards_to_restore = [
        card for card in backup_data 
        if card.get("art_style") in TARGET_STYLES 
        and card.get("labeled_by") == "Human_Audit"
    ]

    if not cards_to_restore:
        print("⚠️ No matching cards found for those styles in the backup.")
        return

    print(f"✨ Found {len(cards_to_restore)} pristine anchors to restore. Pushing to Supabase...")
    
    engine = get_engine()
    success_count = 0
    
    # Use engine.begin() for a secure transaction block
    with engine.begin() as conn:
        for card in cards_to_restore:
            try:
                # Wrap the old string in a list and dump to JSON to match the new architecture
                new_style_format = json.dumps([card["art_style"]])
                
                conn.execute(text("""
                    UPDATE tcg_cards
                    SET art_style = :style,
                        labeled_by = 'Human_Audit',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE card_id = :id
                """), {
                    "style": new_style_format,
                    "id": card["card_id"]
                })
                success_count += 1
            except Exception as e:
                print(f"❌ Failed to restore {card['card_id']}: {str(e)}")

    print(f"🎉 Successfully locked in {success_count} human anchors!")

if __name__ == "__main__":
    # Assumes the JSON file is sitting in your main tcg_tinder folder
    backup_path = os.path.join(root_dir, "supabase_labels_backup.json")
    restore_specific_anchors(backup_path)