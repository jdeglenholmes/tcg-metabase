import time

from src.database.schema import initialise_poke_schemas
from src.database.ops import is_set_already_ingested, upsert_card_data
from src.utils.discovery import fetch_set_list, fetch_card_details

def run_tcg_etl_pipeline(target_sets: list):
    """Systematic ingestion logic with existence checks and rate limiting."""
    initialise_poke_schemas()
    
    for target_set in target_sets:
        set_id = target_set['id']
        
        # --- NEW: Existence Check ---
        if is_set_already_ingested(set_id):
            print(f"⏩ Skipping {target_set['name']} (Already in Database)")
            continue
            
        print(f"\n🚀 Ingesting: {target_set['name']}...")
        cards = fetch_set_list(set_id)
        
        for i, card_summary in enumerate(cards):
            try:
                full_data = fetch_card_details(card_summary['id'])
                upsert_card_data(full_data)
                print(f"   ✅ [{i+1}/{len(cards)}] {full_data['name']}")
                time.sleep(0.3) 
            except Exception as e:
                print(f"   ❌ Error on {card_summary['id']}: {e}")