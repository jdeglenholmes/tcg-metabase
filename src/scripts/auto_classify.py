# src/scripts/auto_classify.py
import sys
import os
import json
import torch
from PIL import Image
import requests
from io import BytesIO
from sqlalchemy import text

# Ensure project root is in path for imports
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from src.dashboard.utils import get_engine, AUTO_STYLES

# --- CLIP One-Liners mapped directly to AUTO_STYLES ---
# These precise strings force CLIP to look for key stylistic signatures
CLIP_PROMPTS = {
    "3d_cgi_render": "a smooth 3d digital portrait, cgi render, modern video game graphic style",
    "sketchbook_comic": "a classic comic book panel illustration, clean line art sketch, pencil drawings with ink crosshatching",
    "heavy_pencil": "a standard graphite pencil drawing, detailed sketch illustration with visible pencil shading textures",
    "heavy_acrylic_oil": "a thick impasto oil painting, textured heavy acrylic paint canvas with visible brush strokes",
    "chalk_pastel": "a soft chalk pastel drawing, smudged textured crayon illustration on rough paper sketch",
    "watercolor_and_ink": "a fluid watercolor painting with soft bleeding pigment, delicate ink linework details"
}

def load_clip_model():
    """Initializes your local CLIP transformer framework."""
    # Assuming transformers library is used locally; adjust if using open_clip
    from transformers import CLIPProcessor, CLIPModel
    
    print("🤖 Loading local CLIP model configurations...")
    model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32")
    processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")
    
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(device)
    return model, processor, device

def fetch_unlabeled_cards(engine):
    """Retrieves batch of eligible target cards from Supabase."""
    query = """
        SELECT card_id, name, image_url 
        FROM tcg_cards 
        WHERE REPLACE(supertype, 'é', 'e') = 'Pokemon' 
          AND image_url IS NOT NULL 
          AND art_style IS NULL
        LIMIT 100;
    """
    with engine.connect() as conn:
        result = conn.execute(text(query)).mappings().fetchall()
    return [dict(row) for row in result]

def main():
    engine = get_engine()
    cards = fetch_unlabeled_cards(engine)
    
    if not cards:
        print("✅ No outstanding unlabeled cards found matching pipeline conditions.")
        return
        
    print(f"📦 Staging {len(cards)} cards for zero-touch classification...")
    model, processor, device = load_clip_model()
    
    # Pre-tokenize our target automated style labels
    labels = [AUTO_STYLES[i] for i in range(len(AUTO_STYLES)) if AUTO_STYLES[i] in CLIP_PROMPTS]
    text_prompts = [CLIP_PROMPTS[label] for label in labels]
    
    for card in cards:
        try:
            # Download card artwork into memory
            response = requests.get(card['image_url'], timeout=10)
            img = Image.open(BytesIO(response.content)).convert("RGB")
            
            # Process tensors
            inputs = processor(
                text=text_prompts, 
                images=img, 
                return_tensors="pt", 
                padding=True
            ).to(device)
            
            with torch.no_grad():
                outputs = model(**inputs)
                # Compute image-to-text softmax classification probabilities
                logits_per_image = outputs.logits_per_image
                probs = logits_per_image.softmax(dim=-1).cpu().numpy()[0]
            
            # Find the highest confidence match
            max_idx = probs.argmax()
            winning_label = labels[max_idx]
            confidence = probs[max_idx]
            
            # Threshold guard: Ensure the classification is meaningful
            if confidence > 0.35:
                print(f"✨ Classified {card['name']} -> {winning_label} ({confidence:.2%})")
                
                with engine.begin() as conn:
                    conn.execute(text("""
                        UPDATE tcg_cards
                        SET art_style = :style,
                            labeled_by = 'Model_Auto',
                            updated_at = CURRENT_TIMESTAMP
                        WHERE card_id = :id
                    """), {
                        "style": json.dumps([winning_label]),
                        "id": card['card_id']
                    })
            else:
                # Flag ambiguous matches for the dynamic discovery dashboard
                print(f"⚠️ Ambiguous composition for {card['name']} (Best: {winning_label} {confidence:.2%}). Routing to Discovery Pool.")
                with engine.begin() as conn:
                    conn.execute(text("""
                        UPDATE tcg_cards
                        SET art_style = :style,
                            labeled_by = 'Model_Ambiguous',
                            updated_at = CURRENT_TIMESTAMP
                        WHERE card_id = :id
                    """), {
                        "style": json.dumps("Manual review needed"),
                        "id": card['card_id']
                    })
                    
        except Exception as e:
            print(f"❌ Failed processing card {card['name']} ({card['card_id']}): {str(e)}")

if __name__ == "__main__":
    main()