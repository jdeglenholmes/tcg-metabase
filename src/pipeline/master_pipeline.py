# src/pipeline/master_pipeline.py
import logging

# IMPORT YOUR ACTUAL ML SCRIPTS HERE
from src.ml.clip_embedder import embed_unembedded_cards
from src.ml.knn_enricher import run_art_style_enrichment

# If you have your OCR script ready, uncomment the line below:
# from src.ml.ocr_cleaner import run_ocr_audit 

logger = logging.getLogger(__name__)

def run_end_to_end_pipeline(target_set=None):
    """
    Executes the full ETL and ML enrichment pipeline using REAL scripts.
    """
    logger.debug(f"==================================================")
    logger.debug(f"🚀 PIPELINE TRIGGERED | Target Set: {target_set or 'BULK SWEEP'}")
    logger.debug(f"==================================================")
    
    stats = {
        "total": 0,
        "embedded": 0,
        "ocr_fixed": 0,
        "knn_enriched": 0
    }
    
    # --- 1. API INGESTION ---
    try:
        if target_set:
            logger.debug(f"Step 1: Attempting to fetch API data for set: {target_set}")
            # stats["total"] = fetch_set(target_set) 
            # Remove the line below once your fetch_set function is wired!
            stats["total"] = "N/A" 
        else:
            logger.debug("Step 1: Bulk Sweep requested. Skipping API fetch phase.")
    except Exception as e:
        logger.error(f"❌ Failed during API Ingestion: {e}", exc_info=True)

    # --- 2. CLIP EMBEDDINGS ---
    try:
        logger.debug("Step 2: Calling embed_unembedded_cards()...")
        stats["embedded"] = embed_unembedded_cards(target_set=target_set)
        logger.debug(f"Step 2 Complete: Successfully embedded {stats['embedded']} cards.")
    except Exception as e:
        logger.error(f"❌ Failed during CLIP embedding: {e}", exc_info=True)

    # --- 3. OCR AUDIT ---
    try:
        logger.debug("Step 3: Calling OCR module...")
        # stats["ocr_fixed"] = run_ocr_audit(target_set=target_set)
        logger.debug(f"Step 3 Complete: OCR skipped or simulated.")
    except Exception as e:
        logger.error(f"❌ Failed during OCR: {e}", exc_info=True)

    # --- 4. KNN ART STYLE ENRICHMENT ---
    try:
        logger.debug("Step 4: Calling run_art_style_enrichment()...")
        stats["knn_enriched"] = run_art_style_enrichment(target_set=target_set)
        logger.debug(f"Step 4 Complete: Successfully enriched {stats['knn_enriched']} cards.")
    except Exception as e:
        logger.error(f"❌ Failed during KNN Enrichment: {e}", exc_info=True)
        
    logger.debug(f"🎉 PIPELINE FINISHED | Final Stats: {stats}")
    logger.debug(f"==================================================")
    
    return stats