import requests
import argparse
from sqlalchemy import text
from src.database.connection import get_engine

def get_missing_sets():
    # 1. Fetch live sets from API
    try:
        response = requests.get("https://api.pokemontcg.io/v2/sets", timeout=10)
        api_sets = {s['id'] for s in response.json().get('data', [])}
    except Exception as e:
        print(f"❌ Failed to fetch from API: {e}")
        return

    # 2. Fetch sets currently in your DB
    engine = get_engine()
    with engine.connect() as conn:
        db_sets = {r[0] for r in conn.execute(text("SELECT DISTINCT set_id FROM tcg_cards")).fetchall() if r[0]}

    # 3. Calculate missing
    missing = api_sets - db_sets
    
    print(f"--- Reconciliation Report ---")
    print(f"Total Sets in API: {len(api_sets)}")
    print(f"Total Sets in DB:  {len(db_sets)}")
    print(f"--- MISSING SETS ({len(missing)}) ---")
    for set_id in sorted(list(missing)):
        print(set_id)

if __name__ == "__main__":
    get_missing_sets()