import argparse
import sys
import requests
import pandas as pd
from sqlalchemy import text
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from src.database.connection import get_engine
from src.ingest.enrichment import run_clip_enrichment_worker
from src.ingest.ground_truth_dict import ground_truth
from src.utils.discovery import resolve_set_id
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.metrics import classification_report, multilabel_confusion_matrix
from sklearn.preprocessing import MultiLabelBinarizer

def run_cli_validation_suite(target_set_id=None, target_set_name=None):
    engine = get_engine()
    lookup_input = target_set_name if target_set_name else target_set_id
    query_id = resolve_set_id(lookup_input)

    print(f"\n🔍 Auditing Set ID: {query_id}")

    
    query = f"SELECT card_id, name, card_aesthetic FROM tcg_cards WHERE set_id = '{query_id}'"
    with engine.connect() as conn:
        db_data = pd.read_sql_query(text(query), conn)

    if db_data.empty:
        print(f"⚠️ No records found for set '{query_id}'.")
        return

    db_data['gt_info'] = db_data['card_id'].map(ground_truth)
    
    # Filter rows that have ground truth data
    val_data = db_data.dropna(subset=['gt_info']).copy()
    
    # --- SANITIZATION ---
    val_data = val_data.dropna(subset=['card_aesthetic'])
    if val_data.empty:
        print("⚠️ No ground truth matches found with valid aesthetic predictions.")
        return

    # --- MULTI-LABEL PREPARATION ---
    # 1. Extract the list of true styles
    val_data['valid_styles'] = val_data['gt_info'].apply(lambda x: x.get('valid_styles', []))
    
    # 2. Wrap the AI's single prediction in a list to match the multi-label format
    val_data['predicted_styles'] = val_data['card_aesthetic'].apply(
        lambda x: str(x).split(',') if pd.notnull(x) and str(x).strip() != '' else []
    )
    
    print(f"\n✅ Audit complete. Validating {len(val_data)} labeled records.")
    
    # --- MULTI-LABEL BINARIZATION ---
    mlb = MultiLabelBinarizer()
    
    # Fit the binarizer on the union of all known and predicted labels
    all_labels = val_data['valid_styles'].tolist() + val_data['predicted_styles'].tolist()
    mlb.fit(all_labels)
    
    # Transform lists into binary arrays (e.g., [0, 1, 0, 1, 0])
    y_true = mlb.transform(val_data['valid_styles'])
    y_pred = mlb.transform(val_data['predicted_styles'])

    # --- 📈 CLASSIFICATION PERFORMANCE REPORT ---
    print("\n--- 📈 MULTI-LABEL CLASSIFICATION REPORT ---")
    print(classification_report(
        y_true, 
        y_pred, 
        target_names=mlb.classes_, 
        zero_division=0
    ))
    
    # --- 📊 MULTI-LABEL CONFUSION MATRICES ---
    # Because a card can be multiple things, we print a 2x2 matrix for EACH class.
    print("\n--- 📊 PER-CLASS CONFUSION MATRICES ---")
    mcm = multilabel_confusion_matrix(y_true, y_pred)
    
    for i, class_name in enumerate(mlb.classes_):
        tn, fp, fn, tp = mcm[i].ravel()
        print(f"\n🏷️  {class_name.upper()}")
        print(f"   True Positives (Hit)     : {tp}")
        print(f"   False Positives (Miss)   : {fp}")
        print(f"   False Negatives (Ignored): {fn}")
        print(f"   True Negatives (Correctly Omitted): {tn}")
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

    # --- SAFETY INTERCEPT ---
    if args.validate and args.set_name and args.set_name.lower() == 'all':
        print("❌ Please provide a specific set to validate.")
        print("💡 Example: make validate SET_NAME=\"151\"")
        sys.exit(0) 
    # ------------------------

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