# src/ingest/enrichment.py
import os
import requests
import torch
import json
import clip
from PIL import Image
from io import BytesIO
from sqlalchemy import text
import logging

from src.database.connection import get_engine

# Attach to the logger we set up in run.py
logger = logging.getLogger('TCG_Ingest')

def run_clip_enrichment_worker(set_prefix=None):
    """
    Finds cards missing image_embeddings, downloads their art, 
    processes them through ViT-B/32, and saves the vectors to PostgreSQL.
    """
    engine = get_engine()
    
    # 1. Build the targeted database query
    query_str = "SELECT card_id, image_url FROM tcg_cards WHERE image_embedding IS NULL AND image_url IS NOT NULL"
    params = {}
    
    # If a specific set was requested (not BULK), filter by it
    if set_prefix and set_prefix != "BULK":
        query_str += " AND set_id ILIKE :set_id"
        params["set_id"] = set_prefix
        
    with engine.connect() as conn:
        cards = conn.execute(text(query_str), params).mappings().fetchall()
        
    if not cards:
        logger.info(f"✅ No unembedded cards found for {set_prefix if set_prefix else 'the entire database'}.")
        return 0

    # 2. Load the Neural Network
    logger.info(f"🧠 Loading ViT-B/32 Vision Model into GPU...")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    
    # Load locally so we retain the critical `preprocess` function
    model_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../ml/models"))
    os.makedirs(model_path, exist_ok=True)
    model, preprocess = clip.load("ViT-B/32", device=device, download_root=model_path)
    
    logger.info(f"⚙️ Model loaded on {device.upper()}. Processing {len(cards)} cards...")
    
    # 3. Process Cards
    headers = {"User-Agent": "TCG-ML-Studio/1.0", "Accept": "image/*"}
    success_count = 0
    
    for i, row in enumerate(cards):
        try:
            # Download Image (with strict timeout so the UI never hangs)
            response = requests.get(row['image_url'], headers=headers, timeout=10)
            if response.status_code != 200:
                logger.warning(f"⚠️ Failed to download image for {row['card_id']} (Status {response.status_code})")
                continue
                
            img = Image.open(BytesIO(response.content)).convert('RGB')
            
            # Generate 512-dimensional Vector
            image_input = preprocess(img).unsqueeze(0).to(device)
            with torch.no_grad():
                image_features = model.encode_image(image_input)
                # Normalize the vector (crucial for accurate Cosine Similarity)
                image_features /= image_features.norm(dim=-1, keepdim=True)
                embedding_vector = image_features.cpu().numpy()[0].tolist()
                
            # Save Vector to Database
            with engine.begin() as conn:
                conn.execute(
                    text("UPDATE tcg_cards SET image_embedding = :emb WHERE card_id = :card_id"),
                    {"emb": json.dumps(embedding_vector), "card_id": row['card_id']}
                )
                
            success_count += 1
            
            # Print a progress update every 10 cards so the Streamlit UI updates live
            if (i + 1) % 10 == 0:
                logger.info(f"   ↳ Embedded {i + 1} / {len(cards)} cards...")
                
        except Exception as e:
            logger.error(f"❌ Failed to embed {row['card_id']}: {e}")
            
    logger.info(f"🎉 Successfully embedded {success_count}/{len(cards)} cards!")
    return success_count