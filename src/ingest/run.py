import argparse
import sys
from src.utils.discovery import discover_tcg_sets, get_rarity_ratio
from src.ingest.etl_upload import run_tcg_etl_pipeline
from src.database.connection import get_engine

# Import standard data tools for the new validation suite
import pandas as pd
from sklearn.metrics import confusion_matrix, classification_report

def run_cli_validation_suite():
    """
    Pulls live classification predictions from the database, compares them 
    against the Option A multi-label Ground Truth array, and logs an accuracy audit.
    """
    print("\n📊 Loading Multi-Label Ground Truth Matrix...")
    
    ground_truth_multi = {
        "me03-059": ["minimalist"], "me03-090": ["minimalist"], "me03-093": ["minimalist"],
        "me03-095": ["minimalist"], "me03-099": ["minimalist"], "sv01-151": ["minimalist"],
        "sv01-210": ["maximalist"], "sv03.5-198": ["maximalist"], "sv04.5-226": ["whimsical"],
        "sv04.5-232": ["minimalist"], "sv04.5-234": ["cinematic", "maximalist"],
        "sv05-183": ["whimsical", "maximalist"], "sv06.5-066": ["cinematic"],
        "sv06.5-069": ["minimalist"], "sv06.5-073": ["cinematic"],
        "sv06.5-077": ["whimsical", "minimalist"], "sv06.5-251": ["cinematic"],
        "sv10-229": ["cinematic"], "sv10-231": ["cinematic"], "sv10-232": ["cinematic"],
        "sv10.5b-105": ["maximalist"], "sv10.5b-116": ["whimsical", "minimalist"],
        "sv10.5b-119": ["maximalist", "whimsical"], "sv10.5b-121": ["maximalist", "whimsical"],
        "sv10.5b-123": ["maximalist"], "sv10.5b-130": ["cinematic"], "sv10.5b-136": ["minimalist"],
        "sv10.5b-142": ["minimalist"], "sv10.5b-144": ["minimalist"], "sv10.5b-169": ["cinematic"],
        "swsh-180": ["maximalist"], "swsh-182": ["whimsical"], "swsh-192": ["whimsical"],
        "swsh-194": ["cinematic"], "swsh5-110": ["maximalist"], "swsh6-203": ["cinematic"],
        "swsh6-205": ["cinematic"], "swsh7-209": ["cinematic"], "swsh7-212": ["cinematic"],
        "swsh10-163": ["whimsical"], "swsh10-172": ["whimsical"], "swsh10-177": ["cinematic"],
        "swsh10-186": ["cinematic"]
    }

    engine = get_engine()
    target_ids = list(ground_truth_multi.keys())

    query = """
        SELECT card_id, name, card_aesthetic 
        FROM tcg_cards 
        WHERE card_id IN :card_ids;
    """

    try:
        with engine.connect() as conn:
            db_data = pd.read_sql_query(query, conn, params={"card_ids": tuple(target_ids)})
    except Exception as e:
        print(f"❌ Database connection error: {e}. Ensure docker containers are up!")
        return

    if db_data.empty:
        print("⚠️  No matching validation records found in 'poke_db'. Run an ingestion loop first!")
        return

    y_true, y_pred = [], []
    partial_credit_hits = 0

    for _, row in db_data.iterrows():
        c_id = row['card_id']
        predicted = row['card_aesthetic']
        allowed_labels = ground_truth_multi[c_id]
        
        if predicted in allowed_labels:
            partial_credit_hits += 1
            y_true.append(predicted)
            y_pred.append(predicted)
        else:
            y_true.append(allowed_labels[0])
            y_pred.append(predicted)

    all_possible_labels = sorted(list(set([lbl for sublist in ground_truth_multi.values() for lbl in sublist])))
    total_evaluated = len(db_data)
    accuracy_pct = (partial_credit_hits / total_evaluated) * 100

    print("=" * 65)
    print(f"🎯 CLIP MODEL FIT AUDIT: {accuracy_pct:.2f}% ({partial_credit_hits}/{total_evaluated} Hits)")
    print("=" * 65)
    print(classification_report(y_true, y_pred, labels=all_possible_labels, zero_division=0))
    print("=" * 65)


def main():
    # 1. Setup Argument Parsing
    parser = argparse.ArgumentParser(description="TCG Poke Research & ETL Tool")
    parser.add_argument("--set_name", type=str, default=None, help="Set name or 'all'")
    parser.add_argument("--series", type=str, default=None, help="Filter by series")
    parser.add_argument("--min_cards", type=int, default=80, help="Minimum card count")
    parser.add_argument("--summary_only", action="store_true", help="Only show discovery summary")
    
    # Argument to control the expensive API rarity sampling
    parser.add_argument("--show_rarity", action="store_true", help="Perform rarity ratio sampling")
    
    # NEW: Core validation arg hook
    parser.add_argument("--validate", action="store_true", help="Run ML pipeline confusion matrix validation")
    
    args = parser.parse_args()

    # 1B. Strategic Split: If --validate flag is tripped, jump straight out of standard ETL pathways
    if args.validate:
        run_cli_validation_suite()
        return

    # Interpret "all" as None to trigger full list logic in discovery.py
    set_name_search = None if args.set_name and args.set_name.lower() == 'all' else args.set_name
    
    # 2. Discovery Phase
    print(f"\n🔍 Searching for TCG sets...")
    matches = discover_tcg_sets(
        target_set_name=set_name_search,
        series_name=args.series,
        min_cards=args.min_cards
    )

    if not matches:
        print("❌ No matching TCG Sets found with those criteria.")
        return

    # 3. Summarized Research View
    targets = [matches[0]] if set_name_search and set_name_search != "all" else matches
    
    print(f"\n📊 Found {len(targets)} TCG Sets matching your criteria.")
    
    name_w = 30  
    series_w = 30
    count_w = 8

    # Print Table Header
    print(f"\n{'NAME':<{name_w}} | {'SERIES':<{series_w}} | {'CARDS':<{count_w}} | {'RARITY RATIO'}")
    print("-" * 110)
    
    # Process and display results
    for s in targets[:10]:
        name = s.get('name', 'Unknown')[:name_w]
        series = s.get('series_name', 'N/A')[:series_w]
        total_cards = s.get('cardCount', {}).get('total', 0)
        
        if args.show_rarity:
            ratio = get_rarity_ratio(s['id'])
        else:
            ratio = "RARITY RATIO not shown. Explicit call needed: '--show_rarity'"
            
        print(f"{name:<{name_w}} | {series:<{series_w}} | {total_cards:<{count_w}} | {ratio}")

    if len(targets) > 10:
        print(f"\n... and {len(targets) - 10} more sets.")

    # 4. Logical Split: Exit if summary_only
    if args.summary_only:
        print(f"\n✅ Corresponding TCG Sets found. Run 'make ingest' to push data to PostgreSQL database.")
        return 

    # 5. Ingestion Phase: Mandatory Confirmation
    print(f"\n🌎 Ready to process {len(targets)} set(s) for database ingestion.")
    confirm = input(f"Proceed with database upload? (Y/N): ").strip().upper()
    
    if confirm == 'Y':
        run_tcg_etl_pipeline(targets)
    else:
        print("🚫 Upload cancelled by user.")

if __name__ == "__main__":
    main()