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
import json
# --- Helper to parse JSONB safely ---
def parse_json_aesthetic(x):
    # 1. If it's already a dict, return it
    if isinstance(x, dict): 
        return x
    
def check_has_trainer_art(card):
    """
    Determines if a card features a trainer in the art alongside a Pokemon.
    """
    # 1. THE SAFETY CATCH: Ignore literal Trainer/Energy cards. 
    # (This stops "Professor Oak's Research" from being flagged)
    if card.get('supertype') != 'Pokémon':
        return False
        
    name_lower = card.get('name', '').lower()
    
    # 2. THE OWNER HEURISTIC (Your logic)
    # Expanded with some classic Gym Leaders and Villain teams!
    known_owners = [
        "brock", "misty", "lt. surge", "erika", "koga", "sabrina", "blaine", "giovanni",
        "team rocket", "rocket", "aqua", "magma", "galactic", "plasma", "flare", "skull",
        "cynthia", "lance", "steven", "n", "lillie", "arven", "iono", "ethan", "red", "blue"
    ]
    
    # Check if the name contains any of the known owners WITH an apostrophe
    if any(f"{owner}'s" in name_lower for owner in known_owners):
        return True
        
    # Optional Bonus: Catch modern "SP" Pokemon from the Platinum era (e.g., "Garchomp C", "Lucario GL")
    # if name_lower.endswith(" c") or name_lower.endswith(" gl"):
    #     return True

    return False
    # 2. If it's a string, try to parse it
    if isinstance(x, str):
        # Clean up any potential 'None' or empty strings
        if not x or x.lower() == 'none':
            return {}
            
        try:
            # Try to parse as JSON (new format)
            return json.loads(x)
        except json.JSONDecodeError:
            # Fallback: Parse as legacy CSV string (e.g., "minimalist,cinematic")
            # We assign 1.0 confidence to legacy labels so they count as "Hits"
            return {style.strip(): 1.0 for style in x.split(',') if style.strip()}
            
    # 3. Fallback for nulls or weird data
    return {}

def is_correct(true_styles, aesthetic_dict, k=3):
    """Checks if any ground truth style exists in the model's Top K predictions."""
    if not aesthetic_dict: return False
    # Sort model output by confidence (the values in the dictionary)
    top_k = sorted(aesthetic_dict.items(), key=lambda x: x[1], reverse=True)[:k]
    top_k_styles = [style for style, score in top_k]
    return any(style in true_styles for style in true_styles if style in top_k_styles)

def run_cli_validation_suite(target_set_id=None, target_set_name=None):
    engine = get_engine()
    lookup_input = target_set_name if target_set_name else target_set_id
    query_id = resolve_set_id(lookup_input) # Assuming this function exists in your src

    print(f"\n🔍 Auditing Set ID: {query_id}")

    query = f"SELECT card_id, name, card_aesthetic FROM tcg_cards WHERE set_id = '{query_id}'"
    with engine.connect() as conn:
        db_data = pd.read_sql_query(text(query), conn)

    if db_data.empty:
        print(f"⚠️ No records found for set '{query_id}'.")
        return

    # Map ground truth
    db_data['gt_info'] = db_data['card_id'].map(ground_truth)
    val_data = db_data.dropna(subset=['gt_info']).copy()
    
    # Parse JSONB and extract valid styles
    val_data['aesthetic_dict'] = val_data['card_aesthetic'].apply(parse_json_aesthetic)
    val_data['valid_styles'] = val_data['gt_info'].apply(lambda x: x.get('valid_styles', []))

    # --- 1. TOP-K ACCURACY REPORT ---
    val_data['is_hit'] = val_data.apply(
        lambda row: is_correct(row['valid_styles'], row['aesthetic_dict'], k=3), axis=1
    )
    
    print(f"\n✅ Audit complete. Validated {len(val_data)} records.")
    print(f"🎯 Top-3 Accuracy: {val_data['is_hit'].mean():.2%}")

    # --- 2. LEGACY BINARY REPORT (For Confusion Matrices) ---
    # We create a threshold (e.g. 0.20) to convert probabilities back to binary 
    # just for the sake of the confusion matrix charts.
    threshold = 0.20
    mlb = MultiLabelBinarizer()
    
    # Binary predictions based on threshold
    val_data['pred_binary'] = val_data['aesthetic_dict'].apply(
        lambda d: [k for k, v in d.items() if v >= threshold]
    )
    
    all_labels = val_data['valid_styles'].tolist() + val_data['pred_binary'].tolist()
    mlb.fit(all_labels)
    
    y_true = mlb.transform(val_data['valid_styles'])
    y_pred = mlb.transform(val_data['pred_binary'])

    print("\n--- 📊 PER-CLASS CONFUSION MATRICES (Threshold >= 20%) ---")
    mcm = multilabel_confusion_matrix(y_true, y_pred)
    
    for i, class_name in enumerate(mlb.classes_):
        tn, fp, fn, tp = mcm[i].ravel()
        print(f"\n🏷️  {class_name.upper()}")
        print(f"   True Positives (Hit)    : {tp}")
        print(f"   False Positives (Miss)  : {fp}")
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

    if args.enrich:
        # Defensive fallback: catch either set_name or set_id just in case
        target = args.set_name if args.set_name else args.set_id
        
        print(f"🔥 DEBUG [run.py]: Captured target '{target}'. Passing to worker...")
        
        run_clip_enrichment_worker(
            batch_size=args.batch_size, 
            force_recompute=args.recompute, 
            set_prefix=target
        )
        
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
            # 2. Fetch Data (Now with Pagination Support)
            print(f"📡 Querying API for set {target_id}...")
            raw_cards = []
            current_page = 1
            page_size = 250

            while True:
                # Dynamically update the page number in the parameters
                params = {
                    "q": f'set.id:"{target_id}"',
                    "page": current_page,
                    "pageSize": page_size
                }
                
                response = session.get("https://api.pokemontcg.io/v2/cards", params=params, timeout=30)
                response.raise_for_status()
                
                page_data = response.json().get("data", [])
                
                # If a page returns completely empty, exit the loop
                if not page_data:
                    break
                    
                raw_cards.extend(page_data)
                print(f"   📄 Fetched page {current_page}: {len(page_data)} cards...")
                
                # If the page returned fewer cards than the maximum limit, we have reached the end
                if len(page_data) < page_size:
                    break
                    
                current_page += 1

            if not raw_cards:
                print(f"❌ API returned empty dataset.")
                return

            print(f"✅ Downloaded {len(raw_cards)} total cards. Starting Upsert...")

            # 3. Dynamic Upsert Loop
            for card in raw_cards:
                
                is_trainer_card = check_has_trainer_art(card)
                
                prices = card.get('tcgplayer', {}).get('prices', {})
                market_price = 0.0
                
                # Extract primary market price
                if 'normal' in prices and 'market' in prices['normal']:
                    market_price = prices['normal']['market']
                elif 'holofoil' in prices and 'market' in prices['holofoil']:
                    market_price = prices['holofoil']['market']
                elif 'reverseHolofoil' in prices and 'market' in prices['reverseHolofoil']:
                    market_price = prices['reverseHolofoil']['market']
                    
                # --- NEW: DERIVE VARIANT FLAGS ---
                # The keys of the 'prices' dictionary tell us exactly which versions of the card exist.
                available_variants = list(prices.keys())
                
                variants_flags = {
                    "normal": "normal" in available_variants,
                    "reverseHolofoil": "reverseHolofoil" in available_variants,
                    "holofoil": "holofoil" in available_variants,
                    "firstEdition": any("1stEdition" in v for v in available_variants)
                }
                # ---------------------------------
                
                enriched_card = {
                    'id': card['id'],
                    'name': card['name'],
                    'is_trainer_card': is_trainer_card, 
                    'illustrator': card.get('artist'),
                    'rarity': card.get('rarity'),
                    'set': {
                        'id': card['set']['id'],
                        'name': card['set']['name'],
                        'series': card['set']['series'],
                        'release_date': card['set'].get('releaseDate'),
                        'total_cards': card['set'].get('total')
                    },
                    'variants': variants_flags,     # Now stores a clean JSON dictionary of True/False flags!
                    'market_price': market_price,   
                    'image_url': card.get('images', {}).get('large'),
                }
                upsert_card_data(enriched_card)
            print(f"🎉 Successfully upserted {len(raw_cards)} records.")
            
        except Exception as e:
            print(f"❌ Ingestion failure: {e}")

if __name__ == '__main__':
    main()