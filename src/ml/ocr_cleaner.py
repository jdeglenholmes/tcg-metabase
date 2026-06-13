# src/ml/ocr_cleaner.py
import os
import requests
import easyocr
import numpy as np
from io import BytesIO
from PIL import Image
from sqlalchemy import text
from tqdm import tqdm
from src.database.connection import get_engine

def main():
    print("="*60)
    print("👁️ COMPUTER VISION GROUND-TRUTH AUDIT")
    print("="*60)

    # Initialize the OCR reader (uses GPU automatically if available)
    print("⚙️ Loading EasyOCR Model...")
    reader = easyocr.Reader(['en'], gpu=True)
    
    engine = get_engine()
    
    # Only fetch cards currently claiming to be 'Pokemon'
    query = """
        SELECT card_id, name, image_url 
        FROM tcg_cards 
        WHERE supertype = 'Pokemon' AND image_url IS NOT NULL;
    """
    
    with engine.connect() as conn:
        result = conn.execute(text(query)).mappings().fetchall()
        
    if not result:
        print("No Pokémon cards found to audit.")
        return

    print(f"🔍 Scanning {len(result)} cards for API mislabels...")
    
    mislabel_count = 0
    pbar = tqdm(result, total=len(result))
    
    for row in pbar:
        try:
            # 1. Download image into memory
            response = requests.get(row['image_url'], timeout=10)
            response.raise_for_status()
            img = Image.open(BytesIO(response.content)).convert('RGB')
            
            # 2. Crop to the top 15% of the card 
            # (Trainer and Energy text is always at the top. This speeds up OCR 
            # and prevents it from reading attack descriptions).
            width, height = img.size
            top_crop = img.crop((0, 0, width, int(height * 0.15)))
            
            # Convert PIL image to numpy array for EasyOCR
            img_array = np.array(top_crop)
            
            # 3. Read the text
            # detail=0 returns just a simple list of text strings found
            detected_text = reader.readtext(img_array, detail=0)
            
            # Convert all found text to uppercase for easy matching
            text_block = " ".join(detected_text).upper()
            
            # 4. Check for ground-truth mislabels
            new_supertype = None
            if "TRAINER" in text_block:
                new_supertype = "Trainer"
            elif "ENERGY" in text_block:
                new_supertype = "Energy"
            elif "ITEM" in text_block:
                new_supertype = "Item"
                
            # 5. Correct the database if a mislabel is found
            if new_supertype:
                mislabel_count += 1
                pbar.set_description(f"🚨 Fixed: {row['name']} -> {new_supertype}")
                
                with engine.begin() as conn:
                    conn.execute(
                        text("UPDATE tcg_cards SET supertype = :supertype WHERE card_id = :card_id;"),
                        {"supertype": new_supertype, "card_id": row['card_id']}
                    )
                    
        except Exception as e:
            pass # Skip silently on download/timeout errors

    print("\n" + "="*60)
    print(f"✅ AUDIT COMPLETE. Successfully corrected {mislabel_count} API mislabels!")
    print("="*60)

if __name__ == "__main__":
    main()