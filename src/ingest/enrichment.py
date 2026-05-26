import httpx
import torch
import torch.nn.functional as F
from PIL import Image
from io import BytesIO
from transformers import CLIPProcessor, CLIPModel

# Initialize lightweight open-source visual model from HuggingFace cache
try:
    MODEL_NAME = "openai/clip-vit-base-patch32"
    processor = CLIPProcessor.from_pretrained(MODEL_NAME)
    model = CLIPModel.from_pretrained(MODEL_NAME)
except Exception as e:
    print(f"⚠️ Warning initializing AI modules: {e}")

def extract_image_features(image_base_url: str) -> list:
    """
    Downloads low-res card asset from CDN and derives a 512-dimension vector array.
    """
    if not image_base_url:
        return None
        
    try:
        # TCGdex fix: Strip any trailing slashes before applying format extensions
        base_clean = image_base_url.rstrip('/')
        target_url = f"{base_clean}/low.webp"
        
        response = httpx.get(target_url, timeout=5.0)
        if response.status_code != 200:
            # Fallback check for missing file format variations
            target_url = f"{base_clean}/low.png"
            response = httpx.get(target_url, timeout=5.0)
            if response.status_code != 200:
                return None
            
        img = Image.open(BytesIO(response.content)).convert("RGB")
        inputs = processor(images=img, return_tensors="pt")
        
        with torch.no_grad():
            outputs = model.get_image_features(**inputs)
            
            # --- IRONCLAD HUGGINGFACE OUTPUT UNPACKING ---
            if hasattr(outputs, 'image_embeds'):
                tensor_features = outputs.image_embeds
            elif hasattr(outputs, 'pooler_output'):
                tensor_features = outputs.pooler_output
            elif hasattr(outputs, 'last_hidden_state'):
                tensor_features = outputs.last_hidden_state[:, 0, :]
            elif isinstance(outputs, torch.Tensor):
                tensor_features = outputs
            else:
                # Direct type extraction fallback
                tensor_features = torch.tensor(outputs)
            
            # Bulletproof L2 Normalization using native functional math
            normalized_features = F.normalize(tensor_features, p=2, dim=-1)
            
        return normalized_features.cpu().numpy()[0].tolist()
    except Exception as e:
        print(f"      ⚠️ Feature extraction skipped for {image_base_url}: {e}")
        return None

def extract_clustering_labels(image_base_url: str, card_name: str) -> dict:
    """
    Uses zero-shot classification via CLIP to dynamically analyze visual traits.
    """
    if not image_base_url:
        return {"art_style": "unknown", "has_trainer": False, "card_aesthetic": "unknown", "pokemon_count": 1, "cameo_pokemon": []}

    try:
        base_clean = image_base_url.rstrip('/')
        target_url = f"{base_clean}/low.webp"
        
        # 1. Download image asset
        response = httpx.get(target_url, timeout=5.0)
        if response.status_code != 200:
            return {"art_style": "unknown", "has_trainer": False, "card_aesthetic": "unknown", "pokemon_count": 1, "cameo_pokemon": []}
            
        img = Image.open(BytesIO(response.content)).convert("RGB")
        
        # 2. Define the classification hypothesis spaces
        aesthetic_labels = ["whimsical cartoon", "dark eerie illustration", "vintage pixel art", "realistic oil painting", "geometric minimalist"]
        art_style_labels = ["classic anime", "3D render", "水彩画 watercolour", "sketch line-art"]
        
        # 3. Run zero-shot classification for Aesthetics
        inputs = processor(text=aesthetic_labels, images=img, return_tensors="pt", padding=True)
        with torch.no_grad():
            outputs = model(**inputs)
        
        # Calculate probabilities via softmax
        logits_per_image = outputs.logits_per_image
        probs = logits_per_image.softmax(dim=-1).cpu().numpy()[0]
        best_aesthetic = aesthetic_labels[probs.argmax()].split()[0] # Grab first descriptor word
        
        # 4. Run zero-shot classification for Art Styles
        inputs_style = processor(text=art_style_labels, images=img, return_tensors="pt", padding=True)
        with torch.no_grad():
            outputs_style = model(**inputs_style)
            
        probs_style = outputs_style.logits_per_image.softmax(dim=-1).cpu().numpy()[0]
        best_style = art_style_labels[probs_style.argmax()].split()[-1]

        # Rule-based heuristics fallback for simple tags
        has_trainer = "trainer" in card_name.lower() or "supporter" in card_name.lower()

        return {
            "art_style": best_style,            
            "has_trainer": has_trainer,            
            "card_aesthetic": best_aesthetic,   
            "pokemon_count": 1,              
            "cameo_pokemon": []              
        }
    except Exception as e:
        return {"art_style": "error", "has_trainer": False, "card_aesthetic": "error", "pokemon_count": 1, "cameo_pokemon": []}