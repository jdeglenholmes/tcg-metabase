import argparse
import sys
from src.utils.discovery import discover_tcg_sets, get_rarity_ratio
from src.ingest.etl_upload import run_tcg_etl_pipeline

def main():
    # 1. Setup Argument Parsing
    parser = argparse.ArgumentParser(description="TCG Poke Research & ETL Tool")
    parser.add_argument("--set_name", type=str, default=None, help="Set name or 'all'")
    parser.add_argument("--series", type=str, default=None, help="Filter by series")
    parser.add_argument("--min_cards", type=int, default=80, help="Minimum card count")
    parser.add_argument("--summary_only", action="store_true", help="Only show discovery summary")
    
    # New argument to control the expensive API rarity sampling
    parser.add_argument("--show_rarity", action="store_true", help="Perform rarity ratio sampling")
    
    args = parser.parse_args()

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
    # If a specific set was searched, focus on that; otherwise show all matches
    targets = [matches[0]] if set_name_search and set_name_search != "all" else matches
    
    print(f"\n📊 Found {len(targets)} TCG Sets matching your criteria.")
    
    # Define Column Widths for the terminal table
    name_w = 30  # Increased slightly to prevent truncation of longer names
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
        
        # Only perform the slow rarity sampling if explicitly requested via --show_rarity
        if args.show_rarity:
            ratio = get_rarity_ratio(s['id'])
        else:
            ratio = "RARITY RATIO not shown. Explicit call needed: 'RARITY=True'.)"
            
        print(f"{name:<{name_w}} | {series:<{series_w}} | {total_cards:<{count_w}} | {ratio}")

    if len(targets) > 10:
        print(f"\n... and {len(targets) - 10} more sets.")

    # 4. Logical Split: Exit if summary_only
    if args.summary_only:
        print(f"\n✅ Corresponding TCG Sets found. Run 'make ingest' to push data to PostreSGL database.")
        return 

    # 5. Ingestion Phase: Mandatory Confirmation
    print(f"\n🌎 Ready to process {len(targets)} set(s) for database ingestion.")
    confirm = input(f"Proceed with database upload? (Y/N): ").strip().upper()
    
    if confirm == 'Y':
        # Hand off to the ETL pipeline
        run_tcg_etl_pipeline(targets)
    else:
        print("🚫 Upload cancelled by user.")

if __name__ == "__main__":
    main()