import os
import sys
import csv
import logging
from sqlalchemy import text
from tqdm import tqdm
from dotenv import load_dotenv

# Ensure project root is in path
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
if sys.path[0] != root_dir:
    sys.path.insert(0, root_dir)

load_dotenv(os.path.join(root_dir, '.env'))
from src.database.connection import get_engine
from src.scripts.vibe_semantic_enricher import sync_illustrator_groups

# --- LOGGING SETUP ---
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(message)s')
logger = logging.getLogger('CSV_Import')

def import_csv_and_update(engine, csv_filepath):
    if not os.path.exists(csv_filepath):
        logger.error(f"❌ Could not find {csv_filepath}")
        return

    # 1. Read the CSV file
    payload = []
    with open(csv_filepath, mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Only add rows where an illustrator was actually found
            artist = row.get('illustrator', '').strip()
            if artist and artist.lower() not in ['unknown', 'null']:
                payload.append({
                    "card_id": row['card_id'].strip(),
                    "illustrator": artist[:100] # Enforce schema limit
                })

    if not payload:
        logger.info("✅ No valid illustrators found in CSV to update.")
        return

    logger.info(f"📥 Loading {len(payload)} manual illustrator corrections...")

    # 2. Execute Bulk Batch Update in a Single Transaction
    # SQLAlchemy converts list-of-dicts into highly optimized bulk DBAPI executions
    update_sql = text("""
        UPDATE public.tcg_cards 
        SET illustrator = :illustrator 
        WHERE card_id = :card_id
    """)

    try:
        with engine.begin() as conn:
            conn.execute(update_sql, payload)
        logger.info(f"🎉 Successfully updated {len(payload)} cards in PostgreSQL!")
    except Exception as e:
        logger.error(f"❌ Bulk update failed: {e}")
        return

    # 3. Trigger Downstream Dimension Sync
    # Ensure any brand-new illustrators from the CSV get categorized by Gemini
    logger.info("🔄 Triggering sync for dim_illustrator_groups...")
    with engine.connect() as conn:
        all_artists = {
            str(row[0]).strip() for row in conn.execute(
                text("SELECT DISTINCT illustrator FROM tcg_cards WHERE illustrator IS NOT NULL")
            ).fetchall()
        }

if __name__ == '__main__':
    engine = get_engine()
    # Assuming you save your CSV in the root/data folder
    csv_path = os.path.join(root_dir, 'data', 'tcg_illustrators.csv')
    import_csv_and_update(engine, csv_path)