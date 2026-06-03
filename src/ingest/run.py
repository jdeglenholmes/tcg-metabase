import argparse
import requests
import pandas as pd
from sqlalchemy import text
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from src.database.connection import get_engine
from src.ingest.etl_upload import run_tcg_etl_pipeline, normalize_set_id
from src.ingest.enrichment import run_clip_enrichment_worker
from src.ingest.ground_truth_dict import ground_truth
from src.utils.discovery import resolve_set_id
from sklearn.metrics import classification_report, confusion_matrix

def run_cli_validation_suite(target_set_id=None, target_set_name=None):
    engine = get_engine()
    lookup_input = target_set_name if target_set_name else target_set_id
    query_id = resolve_set_id(lookup_input)
    
    print(f"\n🔍 Auditing Set ID: {query_id}")

    # 1. Flatten the ground_truth dictionary for O(1) lookup
    flat_gt = {
        card_id: details 
        for theme, cards in ground_truth.items() 
        for card_id, details in cards.items()
    }

    # 2. Query data
    query = f"SELECT card_id, name, card_aesthetic FROM tcg_cards WHERE set_id = '{query_id}'"
    with engine.connect() as conn:
        db_data = pd.read_sql_query(text(query), conn)

    if db_data.empty:
        print(f"⚠️ No records found for set '{query_id}'.")
        return

    # 3. Align with Ground Truth
    db_data['gt_info'] = db_data['card_id'].map(flat_gt)
    
    # Filter rows that have ground truth data
    val_data = db_data.dropna(subset=['gt_info']).copy()
    
    # --- SANITIZATION: Filter out rows where AI hasn't produced an aesthetic ---
    # This prevents the "Classification metrics can't handle a mix of unknown and binary targets" error
    val_data = val_data.dropna(subset=['card_aesthetic'])
    
    if val_data.empty:
        print("⚠️ No ground truth matches found with valid aesthetic predictions.")
        return

    # Extract ground truth styles
    val_data['valid_styles'] = val_data['gt_info'].apply(lambda x: x.get('valid_styles', []))
    val_data['true_primary'] = val_data['valid_styles'].apply(lambda x: x[0] if x else None)
    
    # Final filter: ensure we have both a true label and a predicted label
    val_data = val_data.dropna(subset=['true_primary', 'card_aesthetic'])
    # ADD THIS DIAGNOSTIC PRINT
    print(f"DEBUG: Dataframe shape after filtering: {val_data.shape}")
    if not val_data.empty:
        print(f"DEBUG: Sample aesthetics: {val_data['card_aesthetic'].unique()}")
        print(f"DEBUG: Sample GT styles: {val_data['true_primary'].unique()}")
    else:
        print("DEBUG: val_data is EMPTY after filtering.")
        # Check if the DB IDs actually exist in the GT keys
        missing_ids = db_data[~db_data['card_id'].isin(flat_gt.keys())]
        print(f"DEBUG: {len(missing_ids)} cards from DB have NO ground truth match.")

    # Statistical Reporting
    print(f"\n✅ Audit complete. Validating {len(val_data)} labeled and classified records.")
    
    # --- CLASSIFICATION PERFORMANCE REPORT ---
    # Casting to string ensures sklearn treats all labels as discrete categories
    print("\n--- 📈 CLASSIFICATION PERFORMANCE REPORT ---")
    print(classification_report(
        val_data['true_primary'].astype(str), 
        val_data['card_aesthetic'].astype(str), 
        zero_division=0
    ))
    
    # --- CONFUSION MATRIX ---
    print("\n--- 📊 CONFUSION MATRIX (Primary True vs Predicted) ---")
    labels = sorted(val_data['true_primary'].unique())
    cm = confusion_matrix(
        val_data['true_primary'].astype(str), 
        val_data['card_aesthetic'].astype(str), 
        labels=labels
    )
    print(pd.DataFrame(cm, index=labels, columns=labels))
    
def main():
    parser = argparse.ArgumentParser(description='TCG Poke Research Tool')
    parser.add_argument('--ingest', action='store_true')
    parser.add_argument('--enrich', action='store_true')
    parser.add_argument('--recompute', action='store_true')
    parser.add_argument('--validate', action='store_true')
    parser.add_argument('--set_name', type=str)
    parser.add_argument('--set_id', type=str)
    parser.add_argument('--batch_size', type=int, default=20)
    args = parser.parse_args()

    if args.validate:
        run_cli_validation_suite(target_set_id=args.set_id, target_set_name=args.set_name)
        return

    if args.enrich or args.recompute:
        run_clip_enrichment_worker(batch_size=args.batch_size, force_recompute=args.recompute)
        return

    if args.ingest:
        from src.database.ops import upsert_card_data # Import the new ops
        
        target_id = resolve_set_id(args.set_name) if args.set_name else args.set_id
        if not target_id:
            print(f"❌ Could not resolve ID.")
            return
            
        print(f"🔍 Resolved to API ID: '{target_id}'")
        
        # 1. Setup Session
        session = requests.Session()
        retry = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
        session.mount("https://", HTTPAdapter(max_retries=retry))
        
        try:
            # 2. Fetch Data
            print(f"📡 Querying API...")
            response = session.get("https://api.pokemontcg.io/v2/cards", params={"q": f'set.id:"{target_id}"'}, timeout=30)
            response.raise_for_status()
            
            raw_cards = response.json().get("data", [])
            if not raw_cards:
                print(f"❌ API returned empty dataset.")
                return

            print(f"✅ Downloaded {len(raw_cards)} cards. Starting Upsert...")

            # 3. Dynamic Upsert Loop
            for card in raw_cards:
                # Transform the API structure to match your 'upsert_card_data' expectation
                # (You may need to adjust these keys based on pokemontcg.io API structure)
                enriched_card = {
                    'id': card['id'],
                    'name': card['name'],
                    'illustrator': card.get('artist'),
                    'rarity': card.get('rarity'),
                    'set': {
                        'id': card['set']['id'],
                        'name': card['set']['name'],
                        'series': card['set']['series'],
                        'release_date': card['set'].get('releaseDate'),
                        'total_cards': card['set'].get('total')
                    },
                    'variants': card.get('tcgplayer', {}).get('prices', {}),
                    'market_price': card.get('tcgplayer', {}).get('prices', {}).get('holofoil', {}).get('market', 0),
                    'image_url': card.get('images', {}).get('large'),
                    # ... add other fields like image_embedding if available ...
                }
                upsert_card_data(enriched_card)
                
            print(f"🎉 Successfully upserted {len(raw_cards)} records.")
            
        except Exception as e:
            print(f"❌ Ingestion failure: {e}")

if __name__ == '__main__':
    main()