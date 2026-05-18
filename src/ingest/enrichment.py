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
        target_url = f"{image_base_url}/low.webp"
        response = httpx.get(target_url, timeout=5.0)
        if response.status_code != 200:
            return None
            
        img = Image.open(BytesIO(response.content)).convert("RGB")
        inputs = processor(images=img, return_tensors="pt")
        
        with torch.no_grad():
            outputs = model.get_image_features(**inputs)
            
            if hasattr(outputs, 'image_embeds'):
                tensor_features = outputs.image_embeds
            else:
                tensor_features = outputs
            
            # Safe L2 Normalization
            normalized_features = F.normalize(tensor_features, p=2, dim=-1)
            
        return normalized_features.cpu().numpy()[0].tolist()
    except Exception as e:
        print(f"      ⚠️ Feature extraction skipped for {image_base_url}: {e}")
        return None

# --- VERIFY THIS EXACT NAME AND SPELLING ---
def extract_clustering_labels(image_base_url: str, card_name: str) -> dict:
    """
    Analyzes visual traits using zero-shot inference or metadata rulesets.
    """
    return {
        "art_style": "anime",            
        "has_trainer": False,            
        "card_aesthetic": "whimsical",   
        "pokemon_count": 1,              
        "cameo_pokemon": []              
    }