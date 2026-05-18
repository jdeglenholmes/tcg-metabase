import sys
import time
from tqdm import tqdm
from src.database.schema import initialise_poke_schemas
from src.database.ops import is_set_already_ingested, upsert_card_data
from src.utils.discovery import fetch_set_list, fetch_card_details
from src.ingest.enrichment import extract_image_features, extract_clustering_labels

def run_tcg_etl_pipeline(target_sets: list, batch_size: int = 10):
    """Systematic ingestion logic with manual user confirmation and batch tracking."""
    initialise_poke_schemas()
    
    # 1. Filter out sets that have already been handled to calculate accurate pending work
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

    # 4. Core Processing Loop
    for target_set in pending_sets:
        set_id = target_set['id']
        set_name = target_set['name']
            
        print(f"\n⚡ Ingesting & Analyzing Set: {set_name}")
        cards = fetch_set_list(set_id)
        total_cards = len(cards)
        
        successful_uploads = 0
        failed_uploads = 0
        
        # Wrapped with tqdm for real-time visual progress frames
        with tqdm(total=total_cards, desc=f"📦 Progress [{set_name}]", unit="card", leave=True) as pbar:
            for index, card_summary in enumerate(cards, start=1):
                try:
                    full_data = fetch_card_details(card_summary['id'])
                    print(f"DEBUG keys for {full_data.get('name')}: {list(full_data.keys())}")
                    image_base = full_data.get('image')
                    
                    if image_base:
                        # Derive AI attributes and vectors
                        embedding = extract_image_features(image_base)
                        visual_tags = extract_clustering_labels(image_base, full_data['name'])
                        
                        full_data['image_url'] = f"{image_base}/high.webp"
                        full_data['image_embedding'] = embedding
                        full_data.update(visual_tags)
                    else:
                        full_data['image_url'] = None
                        full_data['image_embedding'] = None
                    
                    # Upsert row to Postgres instance
                    upsert_card_data(full_data)
                    successful_uploads += 1
                    
                except Exception as e:
                    failed_uploads += 1
                    tqdm.write(f"   ❌ Error on card {card_summary.get('id', 'Unknown')}: {e}")
                finally:
                    pbar.update(1)
                
                # Batch Milestone Logging (every 10 cards or at the end of a set)
                if index % batch_size == 0 or index == total_cards:
                    tqdm.write(
                        f"📢 [Batch Checkpoint] Card {index}/{total_cards} processed | "
                        f"Success: {successful_uploads} | Fail: {failed_uploads}"
                    )
                
                time.sleep(0.2) # Courteous sleep to limit API hammering
                
        print(f"🏁 Finished processing {set_name}! Enriched {successful_uploads} cards.\n")