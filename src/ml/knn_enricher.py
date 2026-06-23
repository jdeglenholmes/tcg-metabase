# src/ml/knn_enricher.py
import os
import json
import ast
import logging
import pandas as pd
import numpy as np
from sklearn.neighbors import KNeighborsClassifier
from sqlalchemy import text

from src.database.connection import get_engine

logger = logging.getLogger('TCG_Ingest')

def run_knn_enricher(target_set=None, confidence_threshold=0.70):
    """
    Trains a dynamic KNN classifier using verified database records 
    and classifies unlabeled cards. Gives 5x weight to human-audited anchors.
    """
    engine = get_engine()
    
    # -------------------------------------------------------------------------
    # STEP 1: FETCH & PREPARE TRAINING DATA (THE GOLD STANDARD)
    # -------------------------------------------------------------------------
    logger.info("📥 Fetching training data from database...")
    
    train_query = text("""
        SELECT card_id, art_style, image_embedding, labeled_by 
        FROM tcg_cards 
        WHERE REPLACE(supertype, 'é', 'e') = 'Pokemon' 
          AND art_style IS NOT NULL 
          AND art_style != '"Manual review needed"'
          AND image_embedding IS NOT NULL;
    """)
    
    with engine.connect() as conn:
        train_df = pd.read_sql(train_query, conn)
        
    if train_df.empty:
        logger.warning("⚠️ No training data found. Cannot run KNN enricher.")
        return 0, 0

    # Parse stringified embeddings into numpy arrays safely
    train_df['X'] = train_df['image_embedding'].apply(
        lambda x: ast.literal_eval(x) if isinstance(x, str) else x
    )
    
    # Clean up database JSON quotes (e.g., '"pop_art"' -> 'pop_art')
    train_df['y'] = train_df['art_style'].apply(
        lambda x: json.loads(x) if (isinstance(x, str) and x.startswith('"')) else x
    )

    # --- HUMAN ANCHOR OVERSAMPLING ---
    # Isolate records verified by you to give them massive mathematical gravity
    human_anchors = train_df[train_df['labeled_by'] == 'Human_Audit']
    
    if not human_anchors.empty:
        logger.info(f"⚖️ Found {len(human_anchors)} Human Anchors. Applying 5x gravity multiplier...")
        # Clone your manual adjustments 4 additional times (5x total presence)
        train_df = pd.concat([train_df] + [human_anchors] * 4, ignore_index=True)

    X_train = np.array(train_df['X'].tolist())
    y_train = train_df['y'].values

    # -------------------------------------------------------------------------
    # STEP 2: TRAIN THE WORKHORSE MODEL
    # -------------------------------------------------------------------------
    logger.info("🧠 Training KNeighborsClassifier (Distance-Weighted)...")
    
    # weights='distance' ensures closer vectors scale in importance dramatically
    knn = KNeighborsClassifier(n_neighbors=5, weights='distance')
    knn.fit(X_train, y_train)

    # -------------------------------------------------------------------------
    # STEP 3: FETCH TARGET CARDS (UNLABELED OR SPECIFIC SET)
    # -------------------------------------------------------------------------
    logger.info("🔍 Identifying target cards requiring classification...")
    
    target_query_str = """
        SELECT card_id, image_embedding 
        FROM tcg_cards 
        WHERE REPLACE(supertype, 'é', 'e') = 'Pokemon' 
          AND image_embedding IS NOT NULL
    """
    
    params = {}
    
    # If a specific set is provided, we audit/reclassify everything in that set
    # that hasn't been explicitly locked down by a human or an AI Critic.
    if target_set and target_set != "BULK":
        target_query_str += " AND set_id ILIKE :set_id AND (labeled_by IS NULL OR labeled_by = 'KNN')"
        params["set_id"] = target_set
        logger.info(f"🎯 Target set configured: Filtered by Expansion ID [{target_set}]")
    else:
        # Bulk mode: Sweep only unclassified or machine-uncertain records across the whole DB
        target_query_str += " AND (art_style IS NULL OR art_style = '\"Manual review needed\"')"
        logger.info("🎯 Mode configured: Running global BULK sweep on unclassified queue.")

    with engine.connect() as conn:
        target_df = pd.read_sql(text(target_query_str), conn, params=params)

    if target_df.empty:
        logger.info("✅ Zero target cards found matching criteria. Pipeline complete.")
        return 0, 0

    target_df['X'] = target_df['image_embedding'].apply(
        lambda x: ast.literal_eval(x) if isinstance(x, str) else x
    )
    X_target = np.array(target_df['X'].tolist())

    # -------------------------------------------------------------------------
    # STEP 4: PREDICT AND APPLY THRESHOLDS
    # -------------------------------------------------------------------------
    logger.info(f"🔮 Predicting art styles for {len(target_df)} cards...")
    
    probabilities = knn.predict_proba(X_target)
    max_probs = np.max(probabilities, axis=1)
    predicted_classes = knn.classes_[np.argmax(probabilities, axis=1)]

    auto_classified = 0
    escalated_to_manual = 0

    # -------------------------------------------------------------------------
    # STEP 5: BATCH UPDATE THE DATABASE
    # -------------------------------------------------------------------------
    logger.info("💾 Writing classifications back to Postgres...")
    
    with engine.begin() as conn:
        for idx, row in target_df.iterrows():
            confidence = max_probs[idx]
            
            if confidence >= confidence_threshold:
                final_style = predicted_classes[idx]
                label_source = 'KNN'
                auto_classified += 1
            else:
                final_style = 'Manual review needed'
                label_source = 'KNN_Uncertain'
                escalated_to_manual += 1

            conn.execute(
                text("""
                    UPDATE tcg_cards 
                    SET art_style = :style,
                        labeled_by = :source
                    WHERE card_id = :card_id
                """),
                {
                    "style": json.dumps(final_style),
                    "source": label_source,
                    "card_id": row['card_id']
                }
            )

    logger.info(f"🎉 KNN Enrichment Complete! Automatically Classified: {auto_classified} | Escalated to Audit Station: {escalated_to_manual}")
    return auto_classified, escalated_to_manual