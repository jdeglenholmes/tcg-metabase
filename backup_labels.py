import json
from sqlalchemy import text
from src.database.connection import get_engine

engine = get_engine()

query = "SELECT card_id, art_style, labeled_by FROM tcg_cards WHERE art_style IS NOT NULL;"

with engine.connect() as conn:
    rows = conn.execute(text(query)).mappings().fetchall()
    backup_data = [dict(r) for r in rows]

with open("supabase_labels_backup.json", "w") as f:
    json.dump(backup_data, f, indent=4)

print(f"Successfully backed up {len(backup_data)} rows.")