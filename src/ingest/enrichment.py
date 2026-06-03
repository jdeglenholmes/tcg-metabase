import os
import pandas as pd
from sqlalchemy import text
from tqdm import tqdm
from src.database.connection import get_engine

# --- New Imports for Image Processing & CLIP ---
import requests
from io import BytesIO
from PIL import Image
import torch
import clip
import json

# --- THE CALIBRATED TAXONOMY ---
ART_TAXONOMY_MAPPING = {
    # 1. DUSTBIN (Slightly broadened to catch the generic noise without eating stylized cards)
    # "a standard generic anime trading card, basic 2d character drawing, typical stock illustration": "ignore_standard",
    
    # 2. MINIMALIST (Relaxed the absolute negative constraints so card text doesn't instantly disqualify it)
    "a single character focused on a mostly blank background, very simple clean composition, large areas of empty space, minimal details": "minimalist",
    
    # 3. PASTEL WHIMSICAL (Refined for color and mood)
    "a cute kawaii pastel color palette, soft dreamy fairy tale lighting, charming storybook illustration": "whimsical",
    
    # 4. MAXIMALIST (Pivoted to "environment" to stop it triggering on card text and borders)
    "a densely illustrated wide landscape, a rich environment packed with many small background objects, bustling scenery, highly detailed scene": "maximalist",
    
    # 5. MESSY WATERCOLOR (Simplified to core artistic mediums)
    "a traditional hand-painted watercolor painting, visible brush strokes, wet paint medium, physical art": "traditional_watercolor",
    
    # 6. CRISP DIGITAL (Removed "plastic/glossy" to avoid triggering on holographic foil)
    "a modern 3D rendered character model, clean digital vector art, smooth digital shading, crisp computer graphics": "crisp_digital_portrait",
    
    # 7. CINEMATIC (Left unchanged, holding strong)
    "a dramatic action shot defined by intense atmospheric lighting, glowing particle effects, deep shadows, and a dynamic camera angle": "cinematic",
    
    # 8. HANDCRAFTED (Left unchanged)
    "a physical handcrafted diorama, 3d claymation figure, tactile felt craft model, macro photography of real physical objects and textured materials": "handcrafted_diorama"
}

# --- INITIALIZE CLIP MODEL & TOKENIZER ---
# Force CPU device based on your environment
device = "cpu" 

# Load the standard ViT-B/32 model
model, preprocess = clip.load("ViT-B/32", device=device)

# Pre-tokenize the taxonomy definitions once so they don't re-compute per image
taxonomy_keys = list(ART_TAXONOMY_MAPPING.keys())
text_tokens = clip.tokenize(taxonomy_keys).to(device)

def evaluate_image_with_clip(image_url, card_id):
    """
    Downloads the card image and uses OpenAI's CLIP to classify its aesthetic.
    """
    try:
        # 1. Fetch and Preprocess
        response = requests.get(image_url, timeout=10)
        response.raise_for_status()
        raw_image = Image.open(BytesIO(response.content)).convert("RGB")
        image_input = preprocess(raw_image).unsqueeze(0).to(device)
        
        # 2. Run Inference
        with torch.no_grad():
            
            image_features = model.encode_image(image_input)
            text_features = model.encode_text(text_tokens)
            
            # Normalize the features
            image_features /= image_features.norm(dim=-1, keepdim=True)
            text_features /= text_features.norm(dim=-1, keepdim=True)
            
            # Calculate percentages
            similarity = (100.0 * image_features @ text_features.T).softmax(dim=-1)
            
            # --- 🔍 DIAGNOSTIC X-RAY ---
            # Create a dictionary of all styles and their confidence
            scores = {
                ART_TAXONOMY_MAPPING[taxonomy_keys[i]]: round(similarity[0][i].item(), 3)
                for i in range(len(taxonomy_keys))
            }

            # Write to the dedicated logs directory
            log_path = os.path.join("logs", "clip_diagnostics.log")
            with open(log_path, "a", encoding="utf-8") as log_file:
                log_file.write(f"[{card_id}] {scores}\n")
            # ---------------------------
            
            # 3. Dynamic Thresholding
            max_score = similarity[0].max().item()
            dynamic_threshold = max(0.14, max_score * 0.85)
            
            predicted_tags = []
            for idx, score in enumerate(similarity[0]):
                if score.item() >= dynamic_threshold:
                    matched_key = taxonomy_keys[idx]
                    predicted_tags.append(ART_TAXONOMY_MAPPING[matched_key])
            
            # 4. Fallback (If nothing passes, grab the highest score regardless)
            if len(predicted_tags) == 0:
                best_match_idx = similarity[0].argmax().item()
                predicted_tags.append(ART_TAXONOMY_MAPPING[taxonomy_keys[best_match_idx]])
            
            return ",".join(predicted_tags)
            
    except Exception as e:
        raise RuntimeError(f"CLIP evaluation failed: {e}")

def run_clip_enrichment_worker(batch_size=16, force_recompute=False):
    """
    Phase 2: Pure Vector Compute (Gold Layer).
    Processes pending elements through CLIP with tqdm progress monitoring.
    """
    engine = get_engine()
    
    if force_recompute:
        print("🔄 Force-recompute triggered. Resetting database evaluation flags...")
        
        # --- Safely create directory and clear old log ---
        os.makedirs("logs", exist_ok=True)
        log_path = os.path.join("logs", "clip_diagnostics.log")
        
        if os.path.exists(log_path):
            os.remove(log_path)

        with engine.connect() as conn:
            conn.execute(text(
                    """
                    UPDATE tcg_cards 
                    SET card_aesthetic = :tag, enrichment_status = 'processed' 
                    WHERE card_id = :card_id;
                    """
                    ),
                    {"tag": json.dumps(predicted_tag), "card_id": row['card_id']}
                )
            conn.commit()

    # Highly selective extraction: Only fetch rows that actually need processing
    query = "SELECT card_id, image_url FROM tcg_cards WHERE enrichment_status = 'pending';"
    pending_cards = pd.read_sql_query(query, engine)

    if pending_cards.empty:
        print("⚡ All database assets are up to date. Zero compute cycles wasted.")
        return

    total_pending = len(pending_cards)
    print(f"🧠 Found {total_pending} cards waiting for CLIP taxonomy processing.")

    # Chunk the computation into tracking blocks
    pbar = tqdm(pending_cards.iterrows(), total=len(pending_cards), desc="🚀 Running Inference")
    
    with engine.begin() as conn:
        for _, row in pbar:
            # Update the progress bar description to show current card
            pbar.set_description(f"🚀 Processing: {row['card_id']}")

            try:
                predicted_tag = evaluate_image_with_clip(row['image_url'], row['card_id'])
                json_tag = json.dumps(predicted_tag)
                conn.execute(
                    text("""
                        UPDATE tcg_cards 
                        SET card_aesthetic = :tag, enrichment_status = 'processed' 
                        WHERE card_id = :card_id;
                    """),
                    {"tag": json_tag, "card_id": row['card_id']}
                )
            except Exception as eval_error:
                # tqdm.write preserves the progress bar rendering while printing clean errors
                tqdm.write(f"   ❌ Error processing asset [{row['card_id']}]: {eval_error}")
                conn.execute(
                    text("UPDATE tcg_cards SET enrichment_status = 'failed' WHERE card_id = :card_id;"),
                    {"card_id": row['card_id']}
                )
                continue