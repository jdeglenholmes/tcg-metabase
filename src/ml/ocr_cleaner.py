# src/ml/ocr_cleaner.py
import requests
import easyocr
import numpy as np
from io import BytesIO
from PIL import Image
from sqlalchemy import text
import logging
from src.dashboard.utils import get_engine

logger = logging.getLogger(__name__)

# Global variable to cache the model in memory
_READER = None

def get_reader():
    """Loads the EasyOCR model only once per session."""
    global _READER
    if _READER is None:
        logger.info("Initializing EasyOCR Model (GPU)...")
        _READER = easyocr.Reader(['en'], gpu=True)
    return _READER

def run_ocr_audit(target_set=None):
    """
    Scans card images for mislabeled supertypes (Trainer, Energy, Item).
    Returns the number of database corrections made.
    """
    engine = get_engine()
    reader = get_reader()
    
    query_lines = [
        "SELECT card_id, name, image_url FROM tcg_cards",
        "WHERE supertype = 'Pokemon' AND image_url IS NOT NULL"
    ]
    params = {}
    
    # Obey the UI scope
    if target_set:
        query_lines.append("AND set_id ILIKE :set_id")
        params["set_id"] = target_set
        
    query = text(" ".join(query_lines))
    
    with engine.connect() as conn:
        cards = conn.execute(query, params).mappings().fetchall()
        
    if not cards:
        return 0
        
    mislabel_count = 0
    
    for row in cards:
        try:
            # Download image into memory (using bypass headers)
            headers = {"User-Agent": "TCG-ML-Studio/1.0"}
            resp = requests.get(row['image_url'], headers=headers, timeout=10)
            if resp.status_code != 200:
                continue
                
            img = Image.open(BytesIO(resp.content)).convert('RGB')
            detected_text = reader.readtext(np.array(img), detail=0)
            text_block = " ".join(detected_text).upper()
            
            # Check for API mislabels
            new_supertype = None
            if "TRAINER" in text_block: new_supertype = "Trainer"
            elif "ENERGY" in text_block: new_supertype = "Energy"
            elif "ITEM" in text_block: new_supertype = "Item"
            
            # Correct the database silently
            if new_supertype:
                with engine.begin() as update_conn:
                    update_conn.execute(
                        text("UPDATE tcg_cards SET supertype = :supertype WHERE card_id = :card_id;"),
                        {"supertype": new_supertype, "card_id": row['card_id']}
                    )
                mislabel_count += 1
                
        except Exception as e:
            logger.debug(f"Failed to process {row['card_id']}: {e}")
            
    return mislabel_count