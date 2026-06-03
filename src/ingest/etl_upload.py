import re
import pandas as pd
from tqdm import tqdm
from sqlalchemy import text
from src.database.connection import get_engine

def normalize_set_id(api_id: str) -> str:
    """Standardizes API IDs to match your DB schema (e.g., 'sv06.5')."""
    if not api_id:
        return "unknown"
    match = re.match(r'sv(\d+)(?:pt)(\d+)', api_id)
    if match:
        version = match.group(1).zfill(2)
        part = match.group(2)
        return f"sv{version}.{part}"
    return api_id

def ensure_set_exists(conn, set_id):
    """Prevents ForeignKeyViolation by auto-registering sets."""
    exists = conn.execute(text("SELECT 1 FROM card_sets WHERE set_id = :sid"), {"sid": set_id}).fetchone()
    if not exists:
        conn.execute(text("INSERT INTO card_sets (set_id, name) VALUES (:sid, :name)"), 
                     {"sid": set_id, "name": f"Set {set_id}"})

def run_tcg_etl_pipeline(raw_cards, batch_size=20):
    """
    Standardizes data, ensures relational integrity, and uploads in batches.
    """
    print(f"📥 Processing {len(raw_cards) if isinstance(raw_cards, list) else 'flattened'} records...")
    
    # 1. Unpacking flattened dicts (name__0, card_id__0, etc.)
    if isinstance(raw_cards, dict):
        max_idx = max([int(k.split('__')[1]) for k in raw_cards.keys() if '__' in k], default=0)
        raw_cards = [{
            'id': raw_cards.get(f'card_id__{i}'),
            'name': raw_cards.get(f'name__{i}'),
            'artist': raw_cards.get(f'artist__{i}'),
            'set': {'id': raw_cards.get(f'set_id__{i}')}
        } for i in range(max_idx + 1) if f'card_id__{i}' in raw_cards]

    # 2. Normalization
    processed_cards = []
    for card in raw_cards:
        # Extract and normalize the ID
        api_id = card.get('set', {}).get('id')
        
        # --- FIX: Extracting the image URL correctly ---
        # The API returns card['images']['large']
        img_url = card.get('images', {}).get('large')
        
        processed_cards.append({
            "card_id": card.get('id'),
            "name": card.get('name'),
            "set_id": normalize_set_id(api_id),
            "artist": card.get('artist'),
            "image_url": img_url,  # Ensure this matches your DB column name!
            "enrichment_status": 'pending' # Initialize for your enrichment worker
        })
    
    df = pd.DataFrame(processed_cards)
    
    # 3. Database Upload with Integrity Checks
    engine = get_engine()
    with engine.begin() as conn:
        # Ensure the set exists in the parent table before inserting children
        for sid in df['set_id'].unique():
            ensure_set_exists(conn, sid)
            
        chunks = [df.iloc[i:i + batch_size] for i in range(0, len(df), batch_size)]
        for batch in tqdm(chunks, desc="📦 Uploading Batches"):
            batch.to_sql('tcg_cards', con=conn, if_exists='append', index=False)
            
    print(f"\n✅ Ingestion successful: {len(df)} records committed.")