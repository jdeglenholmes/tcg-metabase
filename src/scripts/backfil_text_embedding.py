import os
import sys
import json
import logging
from sqlalchemy import text
from tqdm import tqdm
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer

# Ensure project root is in import path
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

env_path = os.path.join(root_dir, '.env')
load_dotenv(dotenv_path=env_path)

from src.database.connection import get_engine

# --- LOGGING SETUP ---
if sys.stdout and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(message)s')
logger = logging.getLogger('Backfill')

def run_backfill(engine):
    logger.info("⚙️ Initializing local SentenceTransformer model (Text)...")
    embedder = SentenceTransformer('all-MiniLM-L6-v2')

    # 1. Fetch cards missing text embeddings
    fetch_query = text("""
        SELECT card_id, name, supertype, illustrator, rarity 
        FROM tcg_cards 
        WHERE text_embedding IS NULL
    """)

    update_query = text("""
        UPDATE tcg_cards 
        SET text_embedding = :embedding 
        WHERE card_id = :id
    """)

    with engine.connect() as conn:
        cards = conn.execute(fetch_query).mappings().fetchall()

    if not cards:
        logger.info("✅ All cards already have text embeddings. Nothing to do!")
        return

    logger.info(f"⚡ Found {len(cards)} cards missing text embeddings. Starting local backfill...")

    # 2. Generate and update in isolated transactions
    success_count = 0
    for card in tqdm(cards, desc="Generating Text Vectors", unit="card"):
        try:
            # Recreate the exact string format used in your ingestion script
            text_to_embed = f"{card['name']} | {card['supertype']} | {card['illustrator']} | {card['rarity']}"
            
            # Encode locally and convert to JSON array format for pgvector
            vector = embedder.encode(text_to_embed).tolist()
            embedding_json = json.dumps(vector)

            with engine.begin() as conn:
                conn.execute(update_query, {
                    "embedding": embedding_json,
                    "id": card['card_id']
                })
            
            success_count += 1
        except Exception as e:
            logger.error(f"❌ Failed to update {card['card_id']}: {e}")

    logger.info(f"🎉 Successfully backfilled {success_count}/{len(cards)} cards!")

if __name__ == '__main__':
    engine = get_engine()
    run_backfill(engine)