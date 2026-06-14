# src/ml/knn_enricher.py
import pandas as pd
import numpy as np
import json
import ast
import logging
from sqlalchemy import text
from sklearn.neighbors import KNeighborsClassifier
from src.dashboard.utils import get_engine, ART_STYLE_KEYS

logger = logging.getLogger(__name__)

def run_art_style_enrichment(target_set=None):
    """
    Trains a KNN model on all currently labeled Pokémon cards, 
    then predicts the art style for unlabeled cards.
    """
    engine = get_engine()
    
    # 1. Fetch Training Data (All known labels)
    train_query = text("""
    SELECT art_style, image_embedding 
    FROM tcg_cards 
    WHERE REPLACE(supertype, 'é', 'e') = 'Pokemon' 
      AND art_style IS NOT NULL 
      AND art_style != '"Manual review needed"'
      AND image_embedding IS NOT NULL;
    """)

    target_lines = [
        "SELECT card_id, tags, image_embedding FROM tcg_cards",
        "WHERE REPLACE(supertype, 'é', 'e') = 'Pokemon' AND (art_style IS NULL OR art_style = '\"Manual review needed\"') AND image_embedding IS NOT NULL"
    ]
    params = {}
    if target_set:
        target_lines.append("AND set_id ILIKE :set_id")
        params["set_id"] = target_set
        
    target_query = text("\n".join(target_lines))

    with engine.connect() as conn:
        train_df = pd.read_sql(train_query, conn)
        target_df = pd.read_sql(target_query, conn, params=params)

    if target_df.empty:
        logger.info(f"KNN Enricher: No unlabelled cards found for set '{target_set or 'ALL'}'.")
        return 0

    if train_df.empty:
        logger.error("KNN Enricher: Zero training data found! Cannot run KNN.")
        return 0

    logger.info(f"KNN Enricher: Training on {len(train_df)} known cards. Predicting {len(target_df)} unknown cards...")

    # 3. Parse Embeddings safely
    def parse_emb(val):
        try:
            return ast.literal_eval(val) if isinstance(val, str) else val
        except:
            return None

    train_df['parsed_emb'] = train_df['image_embedding'].apply(parse_emb)
    target_df['parsed_emb'] = target_df['image_embedding'].apply(parse_emb)

    # Drop any rows that failed to parse
    train_df = train_df.dropna(subset=['parsed_emb'])
    target_df = target_df.dropna(subset=['parsed_emb'])

    if target_df.empty:
        return 0

    # 4. Train the Model
    X_train = np.stack(train_df['parsed_emb'].values)
    y_train = train_df['art_style'].values

    knn = KNeighborsClassifier(n_neighbors=5, weights='distance')
    knn.fit(X_train, y_train)

    # 5. Predict
    X_target = np.stack(target_df['parsed_emb'].values)
    probs = knn.predict_proba(X_target)
    max_probs = np.max(probs, axis=1)
    preds = knn.classes_[np.argmax(probs, axis=1)]

    # 6. Apply logic and write to Database
    threshold = 0.60
    update_query = text("UPDATE tcg_cards SET art_style = :style, tags = :tags WHERE card_id = :card_id")
    processed_count = 0

    with engine.begin() as conn:
        for idx, row in target_df.iterrows():
            predicted_style = preds[idx]
            confidence = max_probs[idx]
            
            final_style = predicted_style if confidence >= threshold else "Manual review needed"
            
            # Safely handle the JSON tags column
            try:
                current_tags = json.loads(row['tags']) if isinstance(row['tags'], str) else (row['tags'] or {})
            except Exception:
                current_tags = {}
                
            # Strip out old art styles to prevent multi-tagging mediums
            for k in ART_STYLE_KEYS:
                current_tags.pop(k, None)
                
            # Inject new style if we passed the threshold
            if final_style != "Manual review needed":
                current_tags[final_style] = True

            # FIX: json.dumps() adds the necessary quotes that Postgres requires
            conn.execute(update_query, {
                    "style": json.dumps(final_style),  # This turns 'val' into '"val"'
                    "tags": json.dumps(current_tags),
                    "card_id": row['card_id']
            })
            processed_count += 1

    logger.info(f"KNN Enricher: Successfully mapped {processed_count} cards.")
    return processed_count

if __name__ == "__main__":
    # Configure basic logging to see output in the terminal
    logging.basicConfig(level=logging.DEBUG)
    print("--- KNN Enricher: Starting Manual Execution ---")
    
    # Run the function
    try:
        count = run_art_style_enrichment()
        print(f"--- KNN Enricher: Processed {count} cards ---")
    except Exception as e:
        print(f"--- KNN Enricher: CRASHED with error: {e}")