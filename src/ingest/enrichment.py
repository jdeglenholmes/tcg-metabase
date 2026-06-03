import pandas as pd
from sqlalchemy import text
from tqdm import tqdm
from src.database.connection import get_engine

# Optimized taxonomy dictionary emphasizing composition, line, and background attributes
ART_TAXONOMY_MAPPING = {
    "a minimalist composition with massive empty negative space, a solid simple background, clean uncluttered canvas, and an isolated subject with crisp clean outlines": "minimalist",
    "a complex maximalist composition packed full of overwhelming detail, intricate chaotic patterns, crowded layered backgrounds, and busy action everywhere": "maximalist",
    "a whimsical fairy tale illustration, cute playful fantasy art style, soft dreamy textures, storybook drawing with charming sketch lines": "whimsical",
    "a traditional watercolor painting with soft bleeding edges, translucent fluid washes of paint, visible paper texture, and hand-painted fine art brushstrokes": "traditional_watercolor",
    "a dramatic cinematic shot with intense atmospheric lighting, deep shadows, rich lens blur depth of field, and epic photographic composition": "cinematic",
    "a physical handcrafted diorama, 3d claymation figure, tactile felt craft model, macro photography of real physical objects and textured materials": "handcrafted_diorama",
    "a crisp cgi digital render, clean vector graphic, smooth computer generated art, sharp cel-shaded anime illustration with flawless gradients": "cgi_digital_render"
}

def evaluate_image_with_clip(image_url):
    """
    Placeholder simulating your actual CLIP inference routine.
    Downloads the asset into an in-memory buffer and matches it against tokens.
    """
    # response = requests.get(image_url, timeout=10)
    # img = Image.open(BytesIO(response.content))
    # Run image tensor matching against ART_TAXONOMY_MAPPING keys here...
    return "minimalist"  # Yields predicted aesthetic string label

def run_clip_enrichment_worker(batch_size=16, force_recompute=False):
    """
    Phase 2: Pure Vector Compute (Gold Layer).
    Processes pending elements through CLIP with tqdm progress monitoring.
    """
    engine = get_engine()
    
    if force_recompute:
        print("🔄 Force-recompute triggered. Resetting database evaluation flags...")
        with engine.connect() as conn:
            conn.execute(text("UPDATE tcg_cards SET card_aesthetic = NULL, enrichment_status = 'pending';"))
            conn.commit()

    # Highly selective extraction: Only fetch rows that actually need processing
    query = "SELECT card_id, image_url FROM tcg_cards WHERE enrichment_status = 'pending';"
    pending_cards = pd.read_sql_query(query, engine)

    if pending_cards.empty:
        print("⚡ All database assets are up to date. Zero compute cycles wasted.")
        return

    total_pending = len(pending_cards)
    print(f"🧠 Found {total_pending} cards waiting for CLIP taxonomy processing.")

    # Chunk the computation into tracking blocks monitored by tqdm
    for i in tqdm(range(0, total_pending, batch_size), desc="🚀 Running Inference"):
        batch_df = pending_cards.iloc[i:i + batch_size]

        with engine.begin() as conn:  # Save progress per batch transaction
            for _, row in batch_df.iterrows():
                try:
                    predicted_tag = evaluate_image_with_clip(row['image_url'])
                    
                    conn.execute(
                        text("""
                            UPDATE tcg_cards 
                            SET card_aesthetic = :tag, enrichment_status = 'processed' 
                            WHERE card_id = :card_id;
                        """),
                        {"tag": predicted_tag, "card_id": row['card_id']}
                    )
                except Exception as eval_error:
                    # tqdm.write preserves the progress bar rendering while printing clean errors
                    tqdm.write(f"   ❌ Error processing asset [{row['card_id']}]: {eval_error}")
                    conn.execute(
                        text("UPDATE tcg_cards SET enrichment_status = 'failed' WHERE card_id = :card_id;"),
                        {"card_id": row['card_id']}
                    )
                    continue