# src/ml/clip_embedder.py
import torch
import clip
import requests
import logging
import json
from io import BytesIO
from PIL import Image
from sqlalchemy import text
from src.dashboard.utils import get_engine  # Adjust if your engine is in src.database.connection

logger = logging.getLogger(__name__)

def embed_unembedded_cards(target_set=None):
    """
    Finds cards missing CLIP embeddings, fetches their images, 
    calculates the 512-D vector, and saves it to the database.
    """
    engine = get_engine()
    
    # Update the query in src/ml/clip_embedder.py
    query_lines = [
        "SELECT card_id, image_url FROM tcg_cards",
        "WHERE image_embedding IS NULL AND image_url IS NOT NULL"
        # We remove the hard supertype filter here if you want to embed EVERYTHING,
        # or apply the same REPLACE filter if you ONLY want to embed Pokemon:
        "AND REPLACE(supertype, 'é', 'e') = 'Pokemon'"
    ]
    params = {}
    
    if target_set:
        query_lines.append("AND set_id ILIKE :set_id")
        params["set_id"] = target_set
        
    query = text("\n".join(query_lines))
    
    with engine.connect() as conn:
        result = conn.execute(query, params).mappings().fetchall()
        
    if not result:
        logger.info(f"CLIP Embedder: No missing embeddings found for set '{target_set or 'ALL'}'.")
        return 0

    total_cards = len(result)
    logger.info(f"CLIP Embedder: Found {total_cards} cards requiring embeddings. Loading model...")

    # 2. Load the Vision Model
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model, preprocess = clip.load("ViT-B/32", device=device)
    logger.info(f"CLIP Embedder: Model loaded on {device.upper()}. Starting processing...")

    # 3. Process Images
    processed_count = 0
    update_query = text("UPDATE tcg_cards SET image_embedding = :emb WHERE card_id = :card_id")
    
    with engine.begin() as conn:  # Use transaction for safe batch updating
        for idx, row in enumerate(result):
            card_id = row['card_id']
            img_url = row['image_url']
            
            try:
                # Fetch image into memory
                response = requests.get(img_url, timeout=10)
                response.raise_for_status()
                image = Image.open(BytesIO(response.content)).convert("RGB")
                
                # Preprocess and embed
                image_input = preprocess(image).unsqueeze(0).to(device)
                with torch.no_grad():
                    image_features = model.encode_image(image_input)
                    # Normalize the embedding (crucial for accurate KNN/Cosine Similarity later)
                    image_features /= image_features.norm(dim=-1, keepdim=True)
                
                # Convert tensor to a flat Python list and serialize to JSON string
                embedding_list = image_features.squeeze().cpu().numpy().tolist()
                embedding_json = json.dumps(embedding_list)
                
                # Save to database
                conn.execute(update_query, {"emb": embedding_json, "card_id": card_id})
                processed_count += 1
                
                if processed_count % 50 == 0:
                    logger.info(f"CLIP Embedder: Processed {processed_count}/{total_cards}...")
                    
            except requests.exceptions.RequestException as e:
                logger.warning(f"CLIP Embedder: Failed to download image for {card_id}: {e}")
            except Exception as e:
                logger.error(f"CLIP Embedder: Error embedding card {card_id}: {e}")

    logger.info(f"CLIP Embedder: Completed. Successfully embedded {processed_count}/{total_cards} cards.")
    return processed_count