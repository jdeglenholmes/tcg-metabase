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

# --- MULTI-BODY POKEMON, NOT CAMEOS ---
MULTI_BODY_POKEMON = {
    "binacle": 2, "barbaracle": 7, "dugtrio": 3, "wugtrio": 3, "magneton": 3, 
    "exeggcute": 6, "falinks": 6, "maushold": 4, "tandemaus": 2, "combee": 3, 
    "doduo": 2, "dodrio": 3, "klink": 2, "klang": 3, "klinklang": 4, 
    "zweilous": 2, "hydreigon": 3, "weezing": 2, "cherubi": 2, "vanilluxe": 2,
    "scovillain": 2, "exeggutor": 3
}

# --- 1. SHARPENED ART STYLE TAXONOMY ---
ART_TAXONOMY_MAPPING = {
    "a minimalist illustration with a mostly blank white background, vast empty space, very simple and clean": "minimalist",
    "a chaotic maximalist scene packed with dozens of overlapping background objects, incredibly busy and dense scenery": "maximalist",
   "A traditional hand-painted artwork or physical drawing featuring visible brush strokes, paint layers, canvas texture, paper grain, or analog artistic mediums like watercolor, gouache, oil, acrylic, and ink": "traditional_hand_painted",
    "a highly polished 3D computer render, sharp digital vector graphics, smooth gradients, crisp modern digital art": "crisp_digital_portrait",
    "a dramatic cinematic action shot, extreme lighting, glowing neon particle effects, deep shadows, dynamic camera angle": "cinematic",
    "a physical handcrafted 3D diorama, photographed claymation figure, tactile felt craft model, real world macro photography": "handcrafted_diorama",
    "a bizarre dreamlike surrealist scene, floating objects, irrational juxtaposition, optical illusion, weird and abstract fantasy, dalí style": "surrealist",
    
    # THE FIX: Make the generic class sound basic and flat so it stops stealing the beautiful art
    "a flat cel-shaded anime drawing, basic digital line art, plain standard flat colors, very generic cartoon": "standard_generic",
    "bright vibrant pop art, comic book halftone dots, bold thick black outlines, retro 1960s warhol style, solid flat primary colors": "pop_art",
    "a dynamic comic book illustration, graphic novel art style, bold black ink lines, crosshatching shading details, vibrant superhero comic coloring, cel-shaded": "comic_book_illustration"
}

# --- 2. SHARPENED AESTHETIC TAXONOMY ---
AESTHETIC_TAXONOMY_MAPPING = {
    # THE FIX: Restrict 'kinetic' to actual high-speed attacks, and make 'neutral' attractive to basic poses
    "a high-speed dynamic action shot, extreme motion blur, character aggressively attacking, rapid movement": "kinetic",
    "a dark chaotic and scary scene, aggressive and intimidating, spooky atmosphere, destructive energy": "chaotic",
    "a sleek modern urban aesthetic, contemporary geometric design, stylish and fresh": "modern",
    "a cute whimsical fairy-tale scene, bright pastel colors, magical and playful atmosphere, adorable": "whimsical",
    "an epic legendary scene, majestic and awe-inspiring, god-like aura, massive scale, heroic": "legendary",
    
    # The new baseline for standard standing/posing Pokemon
    "a calm, peaceful, static portrait, character standing still, relaxed natural environment, neutral resting mood": "neutral"
}

print("⚙️ Initializing ML Models...")

# 1. Dynamically detect CUDA
device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"🚀 Computation Device set to: {device.upper()}")

# 2. Load the model
model, preprocess = clip.load("ViT-B/32", device=device)
model = model.half()

# 3. Apply the FP16 (Half-Precision) Optimization
if device == "cuda":
    model = model.half()
    print("⚡ FP16 VRAM Optimization Activated!")

art_keys = list(ART_TAXONOMY_MAPPING.keys())
art_tokens = clip.tokenize(art_keys).to(device)

# Feed the highly descriptive sentences to CLIP instead of basic strings
aes_keys = list(AESTHETIC_TAXONOMY_MAPPING.keys())
aesthetic_tokens = clip.tokenize(aes_keys).to(device)

print("Loading OWLv2 Object Detector for Cameos...")
detector = pipeline(model="google/owlv2-base-patch16-ensemble", task="zero-shot-object-detection")

# --- UPDATE 1: Add Tracers to the Evaluation Function ---
def evaluate_image_with_clip(image_url, card_id, card_name): # <-- Added card_name
    try:
        logging.info(f"🌐 [TRACE] 1. Requesting image from API for {card_id}...")
        response = requests.get(image_url, timeout=10)
        response.raise_for_status()
        raw_image = Image.open(BytesIO(response.content)).convert("RGB")
        width, height = raw_image.size # Get dimensions for spatial filtering
        
        logging.info(f"🧠 [TRACE] 2. Running OWLv2 Object Detection...")
        predictions = detector(
            raw_image, 
            candidate_labels=["pokemon character"],
        )
        
        # --- THE FIX: SPATIAL & TAXONOMY FILTERING ---
        valid_boxes = []
        for box in predictions:
            if box["score"] > 0.15:
                # Get the center point of the detected bounding box
                coords = box['box']
                center_x = (coords['xmin'] + coords['xmax']) / 2
                center_y = (coords['ymin'] + coords['ymax']) / 2
                
                # Spatial Exclusion: Top 25% width and Top 20% height (The Evo Box)
                if center_x < (width * 0.25) and center_y < (height * 0.20):
                    continue # Skip this box entirely!
                    
                valid_boxes.append(box)
        
        # Taxonomy Override: Determine the base entity count for this specific Pokemon
        card_name_lower = card_name.lower()
        base_count = 1
        for mon, count in MULTI_BODY_POKEMON.items():
            if mon in card_name_lower:
                base_count = count
                break
                
        # Total valid entities minus the expected base count = actual cameos
        cameo_count = max(0, len(valid_boxes) - base_count)
        # ---------------------------------------------
        
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
    
    query = "SELECT card_id, image_url, name FROM tcg_cards WHERE enrichment_status = 'pending'"
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
            styles, aesthetics, raw_embedding, cameos = evaluate_image_with_clip(
                row['image_url'], 
                row['card_id'],
                row['name']
                )
            
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