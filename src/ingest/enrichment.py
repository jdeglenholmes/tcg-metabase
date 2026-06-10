import os
import logging
import sys
from sqlalchemy import text
from tqdm import tqdm
from src.database.connection import get_engine
import requests
from io import BytesIO
from PIL import Image
import torch
import clip

os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    filename=os.path.join("logs", "app_log.txt"),
    level=logging.INFO,
    format='[%(asctime)s] %(message)s'
)

print("⚙️ Initializing Vision Model (CLIP)...")
device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"🚀 Computation Device set to: {device.upper()}")

model, preprocess = clip.load("ViT-B/32", device=device)
if device == "cuda":
    model = model.half()

def generate_image_embedding(image_url):
    try:
        response = requests.get(image_url, timeout=10)
        response.raise_for_status()
        raw_image = Image.open(BytesIO(response.content)).convert("RGB")
        
        image_input = preprocess(raw_image).unsqueeze(0).to(device)
        with torch.no_grad():
            image_features = model.encode_image(image_input)
            image_features /= image_features.norm(dim=-1, keepdim=True)
            raw_embedding = image_features[0].cpu().numpy().tolist()
            
        return raw_embedding
    except Exception as e:
        raise RuntimeError(f"Embedding generation failed: {e}")

def run_clip_enrichment_worker(batch_size=16, force_recompute=False, set_prefix=None):
    engine = get_engine()
    
    query = "SELECT card_id, image_url FROM tcg_cards WHERE image_embedding IS NULL AND image_url IS NOT NULL"
    params = {}
    if set_prefix:
        query += " AND card_id ILIKE :set_id"
        params = {"set_id": f"{set_prefix}-%"}
    
    # 🚨 PANDAS REMOVED 🚨 Use pure SQLAlchemy to prevent dict/param mapping crashes
    with engine.connect() as conn:
        result = conn.execute(text(query), params).mappings().fetchall()
    
    if not result:
        print("✅ SUCCESS! All requested cards already have embeddings generated.")
        return

    pbar = tqdm(result, total=len(result), desc="🚀 Generating Embeddings", file=sys.stderr)
    
    for row in pbar:
        pbar.set_description(f"🚀 Processing: {row['card_id']}")
        try:
            raw_embedding = generate_image_embedding(row['image_url'])
            with engine.begin() as conn:
                conn.execute(
                    text("""
                        UPDATE tcg_cards 
                        SET image_embedding = :embedding,
                            enrichment_status = 'processed' 
                        WHERE card_id = :card_id;
                    """),
                    {
                        "embedding": str(raw_embedding),
                        "card_id": row['card_id']
                    }
                )
        except Exception as eval_error:
            tqdm.write(f"   ❌ Error processing asset [{row['card_id']}]: {eval_error}")
            with engine.begin() as conn:
                conn.execute(
                    text("UPDATE tcg_cards SET enrichment_status = 'failed' WHERE card_id = :card_id;"),
                    {"card_id": row['card_id']}
                )