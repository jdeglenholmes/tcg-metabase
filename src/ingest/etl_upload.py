import sys
import time
from tqdm import tqdm
from src.database.schema import initialise_poke_schemas
from src.database.ops import is_set_already_ingested, upsert_card_data
from src.utils.discovery import fetch_set_list, fetch_card_details
from src.ingest.enrichment import extract_image_features, extract_clustering_labels

def run_tcg_etl_pipeline(target_sets: list, batch_size: int = 10):
    """
    Systematic ingestion logic with manual user confirmation, visual progress metrics,
    and automated multimodal AI attribute enrichment.
    """
    # Force schema and pgvector extension verification before beginning transactional workflows
    initialise_poke_schemas()
    
    # 1. Calculate an accurate manifest of pending sets to prevent duplicate work
    pending_sets = [s for s in target_sets if not is_set_already_ingested(s['id'])]
    
    if not pending_sets:
        print("\n⏩ All targeted TCG sets are already fully ingested in PostgreSQL. Nothing to do!")
        return

    # 2. Display a clear pre-ingest manifest summary
    print("\n========================================================")
    print("📋 MULTIMODAL INGESTION MANIFEST")
    print("========================================================")
    print(f"Total Sets Pending: {len(pending_sets)}")
    for s in pending_sets:
        print(f"  • {s['name']} ({s.get('series_name', 'N/A')} Series)")
    print("========================================================")
    print("⚠️  WARNING: Ingestion downloads images and computes dense vector")
    print("   embeddings via deep learning (CLIP). This can be CPU intensive.")
    print("========================================================")
    
    # 3. Intercept execution for human-in-the-loop confirmation
    user_confirm = input("❓ Proceed with multimodal data ingestion? (y/N): ").strip().lower()
    if user_confirm not in ['y', 'yes']:
        print("\n🛑 Ingestion aborted by user. Exiting cleanly.")
        sys.exit(0)
        
    print("\n🚀 Starting pipeline ingestion...")

    # 4. Core Multimodal Processing Loop
    for target_set in pending_sets:
        set_id = target_set['id']
        set_name = target_set['name']
            
        print(f"\n⚡ Ingesting & Analyzing Set: {set_name}")
        cards = fetch_set_list(set_id)
        total_cards = len(cards)
        
        successful_uploads = 0
        failed_uploads = 0
        
        # Wrapped with tqdm for real-time visual progress frames in terminal
        with tqdm(total=total_cards, desc=f"📦 Progress [{set_name}]", unit="card", leave=True) as pbar:
            for index, card_summary in enumerate(cards, start=1):
                try:
                    full_data = fetch_card_details(card_summary['id'])
                    image_base = full_data.get('image')
                    
                    if image_base:
                        # Clean base string to avoid edge-case double-slashes on CDN paths
                        image_base_clean = image_base.rstrip('/')
                        
                        # Derive AI attributes and vectors via CLIP model towers
                        embedding = extract_image_features(image_base_clean)
                        visual_tags = extract_clustering_labels(image_base_clean, full_data.get('name', 'Unknown'))
                        
                        full_data['image_url'] = f"{image_base_clean}/high.webp"
                        full_data['image_embedding'] = embedding
                        full_data.update(visual_tags)
                    else:
                        full_data['image_url'] = None
                        full_data['image_embedding'] = None
                    
                    # Atomic upsert row step to local Postgres instance
                    upsert_card_data(full_data)
                    successful_uploads += 1
                    
                except Exception as e:
                    failed_uploads += 1
                    tqdm.write(f"   ❌ Error processing card {card_summary.get('id', 'Unknown')}: {e}")
                finally:
                    pbar.update(1)
                
                # Batch Milestone Checkpoint Logs (prevents stdout overflow)
                if index % batch_size == 0 or index == total_cards:
                    tqdm.write(
                        f"📢 [Batch Checkpoint] Card {index}/{total_cards} processed | "
                        f"Success: {successful_uploads} | Fail: {failed_uploads}"
                    )
                
                # Courteous sleep to limit upstream API hammering
                time.sleep(0.2)
                
        print(f"🏁 Finished processing {set_name}! Enriched {successful_uploads} cards.\n")