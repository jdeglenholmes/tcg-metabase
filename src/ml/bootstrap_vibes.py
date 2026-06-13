# src/ml/bootstrap_vibes.py
import os
import json
import ast
import torch
import clip
import pandas as pd
from sqlalchemy import text
from src.database.connection import get_engine

def main():
    print("="*60)
    print("✨ ZERO-SHOT VIBE BOOTSTRAPPER")
    print("="*60)
    
    text_prompt = input("Enter the visual prompt (e.g., 'A card with an eerie gothic vibe'): ")
    target_tag = input("Enter the exact tag name to save to DB (e.g., 'eerie_gothic'): ")
    top_n = int(input("How many top cards do you want to auto-label? (e.g., 50): "))

    print("\n⚙️ Initializing Vision Model (CLIP)...")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model, preprocess = clip.load("ViT-B/32", device=device)

    print("\n📦 Fetching existing embeddings from database...")
    engine = get_engine()
    
    # Fetch all Pokémon cards with existing visual embeddings
    query = """
        SELECT card_id, name, tags, image_embedding 
        FROM tcg_cards 
        WHERE image_embedding IS NOT NULL
        AND supertype IN ('Pokémon', 'Pokemon');
    """
    
    with engine.connect() as conn:
        df = pd.read_sql(text(query), conn)

    if df.empty:
        print("❌ No embeddings found. Please run the enrichment script first.")
        return

    print("🧠 Parsing 512-D visual embeddings...")
    df['image_embedding'] = df['image_embedding'].apply(ast.literal_eval)
    
    # Convert DB embeddings into a Torch tensor
    image_features = torch.tensor(df['image_embedding'].tolist(), dtype=torch.float32).to(device)
    
    print(f"🔍 Analyzing dataset for: '{text_prompt}'...")
    text_input = clip.tokenize([text_prompt]).to(device)
    
    with torch.no_grad():
        text_features = model.encode_text(text_input)
        text_features /= text_features.norm(dim=-1, keepdim=True)
        
        # Calculate Cosine Similarity to find the best vibe matches
        similarities = (image_features @ text_features.T).squeeze(1)
        
    df['similarity_score'] = similarities.cpu().numpy()
    
    # Get top N highest scoring cards
    top_matches = df.sort_values(by='similarity_score', ascending=False).head(top_n)
    
    print(f"\n🏆 Top {top_n} Matches Found!")
    for idx, row in top_matches.head(10).iterrows():
        print(f"   ↳ [{row['card_id']}] {row['name']} (Score: {row['similarity_score']:.3f})")
        
    confirm = input(f"\n❓ Do you want to inject the '{target_tag}' tag as True for these {top_n} cards? (y/n): ")
    if confirm.lower() != 'y':
        print("Aborting database update.")
        return
        
    print(f"💾 Updating database...")
    with engine.begin() as conn:
        for idx, row in top_matches.iterrows():
            current_tags = row['tags']
            if current_tags is None:
                current_tags = {}
            elif isinstance(current_tags, str):
                current_tags = json.loads(current_tags)
                
            # Inject the new label
            current_tags[target_tag] = True
            
            update_query = text("""
                UPDATE tcg_cards 
                SET tags = :tags, 
                    updated_at = CURRENT_TIMESTAMP
                WHERE card_id = :card_id;
            """)
            
            conn.execute(update_query, {
                "tags": json.dumps(current_tags),
                "card_id": row['card_id']
            })
            
    print("✅ Successfully bootstrapped new tags! You can now run train_model.py")

if __name__ == "__main__":
    main()