import os
import logging
import pandas as pd
import sys
from sqlalchemy import text
from tqdm import tqdm
from src.database.connection import get_engine
import requests
from io import BytesIO
from PIL import Image
import torch
import clip
import json
from transformers import pipeline

# --- CONFIGURE THE LOGGER ---
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    filename=os.path.join("logs", "app_log.txt"),
    level=logging.INFO,
    format='[%(asctime)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# --- 1. THE UPDATED ART STYLE TAXONOMY ---
ART_TAXONOMY_MAPPING = {
    "a single character focused on a mostly blank background, very simple clean composition, large areas of empty space, minimal details": "minimalist",
    "a densely illustrated wide landscape, a rich environment packed with many small background objects, bustling scenery, highly detailed scene": "maximalist",
    "a traditional hand-painted watercolor painting, visible brush strokes, wet paint medium, physical art": "traditional_watercolor",
    "a modern 3D rendered character model, clean digital vector art, smooth digital shading, crisp computer graphics": "crisp_digital_portrait",
    "a dramatic action shot defined by intense atmospheric lighting, glowing particle effects, deep shadows, and a dynamic camera angle": "cinematic",
    "a physical handcrafted diorama, 3d claymation figure, tactile felt craft model, macro photography of real physical objects and textured materials": "handcrafted_diorama",
    # NEW ADDITION: Painterly
    "a rich textured painting, visible thick brush strokes, acrylic or oil paint style, highly artistic and expressive canvas": "painterly",
    # --- NEW ESCAPE HATCH CLASSES ---
    "a standard anime style character illustration, generic trading card game artwork, basic 2d pose, standard digital coloring": "standard_generic",
    "a highly unusual, bizarre, or experimental art style, abstract, mixed media, completely unique and defying standard categories": "other_unique"
}

# --- 2. THE NEW AESTHETIC TAXONOMY ---
AESTHETIC_TAXONOMY_MAPPING = {
    "a sense of intense speed, movement, and explosive action, dynamic energy": "kinetic",
    "a visually overwhelming and chaotic scene, messy, destructive, or wild energy": "chaotic",
    "a sleek, modern, highly polished, and contemporary aesthetic, clean lines": "modern",
    "a cute, whimsical, dreamy, magical, and lighthearted mood, soft and playful": "whimsical",
    "an epic, awe-inspiring, mythological, and legendary atmosphere, godly power": "legendary",
    "a standard, neutral presentation, basic everyday feeling, calm and unremarkable mood, straightforward and generic vibe": "neutral"
}

device = "cpu" 
model, preprocess = clip.load("ViT-B/32", device=device)

art_keys = list(ART_TAXONOMY_MAPPING.keys())
art_tokens = clip.tokenize(art_keys).to(device)

# Feed the highly descriptive sentences to CLIP instead of basic strings
aes_keys = list(AESTHETIC_TAXONOMY_MAPPING.keys())
aesthetic_tokens = clip.tokenize(aes_keys).to(device)

print("Loading OWLv2 Object Detector for Cameos...")
detector = pipeline(model="google/owlv2-base-patch16-ensemble", task="zero-shot-object-detection")

# --- UPDATE 1: Add Tracers to the Evaluation Function ---
def evaluate_image_with_clip(image_url, card_id):
    try:
        logging.info(f"🌐 [TRACE] 1. Requesting image from API for {card_id}...")
        response = requests.get(image_url, timeout=10)
        response.raise_for_status()
        raw_image = Image.open(BytesIO(response.content)).convert("RGB")
        
        logging.info(f"🧠 [TRACE] 2. Running OWLv2 Object Detection...")
        predictions = detector(
            raw_image, 
            candidate_labels=["pokemon character"],
        )
        valid_boxes = [box for box in predictions if box["score"] > 0.15]
        cameo_count = max(0, len(valid_boxes) - 1)
        
        logging.info(f"🖼️ [TRACE] 3. Running CLIP zero-shot evaluation...")
        image_input = preprocess(raw_image).unsqueeze(0).to(device)
        
        with torch.no_grad():
            image_features = model.encode_image(image_input)
            raw_embedding = image_features[0].cpu().numpy().tolist()
            image_features /= image_features.norm(dim=-1, keepdim=True)
            
            # Art Style
            art_features = model.encode_text(art_tokens)
            art_features /= art_features.norm(dim=-1, keepdim=True)
            art_similarity = (100.0 * image_features @ art_features.T).softmax(dim=-1)
            
            max_art_score = art_similarity[0].max().item()
            art_threshold = max(0.14, max_art_score * 0.85)
            
            predicted_styles = []
            for idx, score in enumerate(art_similarity[0]):
                if score.item() >= art_threshold:
                    predicted_styles.append(ART_TAXONOMY_MAPPING[art_keys[idx]])
                    
            if not predicted_styles:
                predicted_styles.append(ART_TAXONOMY_MAPPING[art_keys[art_similarity[0].argmax().item()]])

            # Aesthetic
            aes_features = model.encode_text(aesthetic_tokens)
            aes_features /= aes_features.norm(dim=-1, keepdim=True)
            aes_similarity = (100.0 * image_features @ aes_features.T).softmax(dim=-1)
            top_aesthetic = AESTHETIC_TAXONOMY_MAPPING[aes_keys[aes_similarity[0].argmax().item()]]
            
            logging.info(f"✅ [TRACE] 4. ML evaluation complete.")
            return predicted_styles, [top_aesthetic], raw_embedding, cameo_count
            
    except Exception as e:
        raise RuntimeError(f"CLIP evaluation failed: {e}")

# Update the definition
def run_clip_enrichment_worker(batch_size=16, force_recompute=False, set_prefix=None):
    engine = get_engine()
    
    print(f"🔥 DEBUG [enrichment.py]: Worker received target '{set_prefix}'. Building query...")
    
    query = "SELECT card_id, image_url FROM tcg_cards WHERE enrichment_status = 'pending'"
    params = {}
    
    if set_prefix:
        query += " AND set_id ILIKE :set_id"
        params = {"set_id": set_prefix}
    
    with engine.connect() as conn:
        pending_cards = pd.read_sql_query(text(query), conn, params=params)
    
    if pending_cards.empty:
        print(f"❌ DEBUG [enrichment.py]: FAILED! Found 0 cards.")
        print(f"   Query executed: {query}")
        print(f"   Params used: {params}")
        return
    else:
        print(f"✅ DEBUG [enrichment.py]: SUCCESS! Found {len(pending_cards)} cards. Starting tqdm loop...")

    # 2. Setup the single progress bar and the transaction
    # We use file=sys.stderr so your run_pipeline_live function can capture the updates!
    pbar = tqdm(pending_cards.iterrows(), total=len(pending_cards), desc="🚀 Running Inference", file=sys.stderr)
    
    # REMOVED the 'with engine.begin()' from here!
    
    for _, row in pbar:
        pbar.set_description(f"🚀 Processing: {row['card_id']}")

        try:
            # Capture tags (Takes 30-60s)
            styles, aesthetics, raw_embedding, cameos = evaluate_image_with_clip(row['image_url'], row['card_id'])
            
            # OPEN THE TRANSACTION HERE (Commits instantly when the block finishes)
            with engine.begin() as conn:
                conn.execute(
                    text("""
                        UPDATE tcg_cards 
                        SET art_style = :style, 
                            card_aesthetic = :aesthetic,
                            image_embedding = :embedding,
                            cameos = :cameo_count,
                            enrichment_status = 'processed' 
                        WHERE card_id = :card_id;
                    """),
                    {
                        "style": json.dumps(styles), 
                        "aesthetic": json.dumps(aesthetics), 
                        "embedding": str(raw_embedding),
                        "cameo_count": cameos,
                        "card_id": row['card_id']
                    }
                )

        except Exception as eval_error:
            tqdm.write(f"   ❌ Error processing asset [{row['card_id']}]: {eval_error}")
            
            # Also safely isolate the error update
            with engine.begin() as conn:
                conn.execute(
                    text("UPDATE tcg_cards SET enrichment_status = 'failed' WHERE card_id = :card_id;"),
                    {"card_id": row['card_id']}
                )