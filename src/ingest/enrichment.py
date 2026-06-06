import os
import pandas as pd
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

# --- 1. THE UPDATED ART STYLE TAXONOMY ---
ART_TAXONOMY_MAPPING = {
    "a single character focused on a mostly blank background, very simple clean composition, large areas of empty space, minimal details": "minimalist",
    "a densely illustrated wide landscape, a rich environment packed with many small background objects, bustling scenery, highly detailed scene": "maximalist",
    "a traditional hand-painted watercolor painting, visible brush strokes, wet paint medium, physical art": "traditional_watercolor",
    "a modern 3D rendered character model, clean digital vector art, smooth digital shading, crisp computer graphics": "crisp_digital_portrait",
    "a dramatic action shot defined by intense atmospheric lighting, glowing particle effects, deep shadows, and a dynamic camera angle": "cinematic",
    "a physical handcrafted diorama, 3d claymation figure, tactile felt craft model, macro photography of real physical objects and textured materials": "handcrafted_diorama",
    # NEW ADDITION: Painterly
    "a rich textured painting, visible thick brush strokes, acrylic or oil paint style, highly artistic and expressive canvas": "painterly"
}

# --- 2. THE NEW AESTHETIC TAXONOMY ---
AESTHETIC_KEYS = ["kinetic", "chaotic", "modern", "whimsical", "legendary"]

device = "cpu" 
model, preprocess = clip.load("ViT-B/32", device=device)

art_keys = list(ART_TAXONOMY_MAPPING.keys())
art_tokens = clip.tokenize(art_keys).to(device)

# Provide a slight contextual prompt for the aesthetics
aesthetic_prompts = [f"This trading card art feels very {a}." for a in AESTHETIC_KEYS]
aesthetic_tokens = clip.tokenize(aesthetic_prompts).to(device)

print("Loading OWLv2 Object Detector for Cameos...")
detector = pipeline(model="google/owlv2-base-patch16-ensemble", task="zero-shot-object-detection")

def evaluate_image_with_clip(image_url, card_id):
    """Evaluates image for both Art Style and Aesthetic."""
    try:
        response = requests.get(image_url, timeout=10)
        response.raise_for_status()
        raw_image = Image.open(BytesIO(response.content)).convert("RGB")
        
        # --- NEW: COUNT CAMEOS WITH OWLV2 ---
        # We do this first while we have the raw_image ready
        predictions = detector(
            raw_image, 
            candidate_labels=["pokemon character"],
        )
        # Filter for confident detections. (0.15 to 0.20 is a good sweet spot for drawn art)
        valid_boxes = [box for box in predictions if box["score"] > 0.15]
        
        # Total entities minus 1 (the main character) = cameos. Keep it at 0 minimum.
        cameo_count = max(0, len(valid_boxes) - 1)
        # -------------------------------------
        
        image_input = preprocess(raw_image).unsqueeze(0).to(device)
        
        with torch.no_grad():
            image_features = model.encode_image(image_input)
            
            # Extract raw embedding
            raw_embedding = image_features[0].cpu().numpy().tolist()
            
            # Normalize
            image_features /= image_features.norm(dim=-1, keepdim=True)
            
            # --- EVALUATE ART STYLE ---
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

            # --- EVALUATE AESTHETIC ---
            aes_features = model.encode_text(aesthetic_tokens)
            aes_features /= aes_features.norm(dim=-1, keepdim=True)
            aes_similarity = (100.0 * image_features @ aes_features.T).softmax(dim=-1)
            
            # Just grab the top aesthetic to keep it simple
            top_aesthetic = AESTHETIC_KEYS[aes_similarity[0].argmax().item()]
            
            # Return both as Python lists/strings (will be formatted beautifully by JSON dumps)
            return predicted_styles, [top_aesthetic], raw_embedding, cameo_count
            
    except Exception as e:
        raise RuntimeError(f"CLIP evaluation failed: {e}")

def run_clip_enrichment_worker(batch_size=16, force_recompute=False):
    engine = get_engine()
    
    if force_recompute:
        print("🔄 Force-recompute triggered. Resetting database evaluation flags...")
        os.makedirs("logs", exist_ok=True)
        log_path = os.path.join("logs", "clip_diagnostics.log")
        if os.path.exists(log_path):
            os.remove(log_path)

        # FIXED BUG: Safely reset all cards to pending so they can be re-run
        with engine.begin() as conn:
            conn.execute(text("UPDATE tcg_cards SET enrichment_status = 'pending';"))

    query = "SELECT card_id, image_url FROM tcg_cards WHERE enrichment_status = 'pending';"
    pending_cards = pd.read_sql_query(query, engine)

    if pending_cards.empty:
        print("⚡ All database assets are up to date. Zero compute cycles wasted.")
        return

    total_pending = len(pending_cards)
    print(f"🧠 Found {total_pending} cards waiting for CLIP taxonomy processing.")

    pbar = tqdm(pending_cards.iterrows(), total=len(pending_cards), desc="🚀 Running Inference")
    
    with engine.begin() as conn:
        for _, row in pbar:
            pbar.set_description(f"🚀 Processing: {row['card_id']}")

            try:
                
                # Capture both tags
                styles, aesthetics, raw_embedding, cameos = evaluate_image_with_clip(row['image_url'], row['card_id'])
                
                # json.dumps on a list creates perfectly formatted arrays: '["painterly", "traditional_watercolor"]'
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
                conn.execute(
                    text("UPDATE tcg_cards SET enrichment_status = 'failed' WHERE card_id = :card_id;"),
                    {"card_id": row['card_id']}
                )
                continue