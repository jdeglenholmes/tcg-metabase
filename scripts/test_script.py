import os
from sqlalchemy import text
from src.utils.discovery import resolve_set_id
from src.ingest.run import get_engine

def test_full_pipeline(user_input):
    print(f"\n--- Testing Pipeline for: '{user_input}' ---")
    
    # 1. Verify DB Connection
    engine = get_engine()
    print(f"DEBUG: Connecting to DB at: {engine.url}")
    
    # 2. Resolve to Canonical ID
    canon_id = resolve_set_id(user_input)
    print(f"DEBUG: Resolved '{user_input}' to '{canon_id}'")
    
    # 3. Check DB Health
    with engine.connect() as conn:
        # Check if table even exists and what it contains
        total_rows = conn.execute(text("SELECT COUNT(*) FROM tcg_cards")).scalar()
        print(f"DEBUG: Total cards in DB: {total_rows}")
        
        # Check for the specific ID
        query = text("SELECT COUNT(*) FROM tcg_cards WHERE set_id = :sid")
        result = conn.execute(query, {"sid": canon_id}).scalar()
        
        print(f"Database found {result} cards for ID '{canon_id}'.")
        
        # Optional: Print all IDs found if result is 0
        if result == 0:
            all_ids = conn.execute(text("SELECT DISTINCT set_id FROM tcg_cards")).fetchall()
            print(f"DEBUG: IDs present in DB: {[row[0] for row in all_ids]}")
            
    assert result > 0, f"Failure: No records found in DB for {canon_id}"
    print(f"✅ Success: Pipeline verified for {canon_id}")

if __name__ == "__main__":
    # Test your standardized IDs
    try:
        test_full_pipeline("shrouded-fable")
        test_full_pipeline("151")
    except Exception as e:
        print(f"\n❌ Test Failed with error: {e}")