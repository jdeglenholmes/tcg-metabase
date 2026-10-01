import pandas as pd
from sqlalchemy import text
from src.database.connection import get_engine

# 1. Read the file
df = pd.read_csv('../Data/pokemon.csv', encoding='utf-16', sep='\t')

# 2. Rename columns to match existing schema
df['pokedex_number'] = df['national_number']
df['pokemon_name'] = df['english_name']

# Drop old columns so they don't interfere
df.drop(columns=['national_number', 'english_name'], inplace=True, errors='ignore')

# 3. Clean NaN values (Explicitly setting them to None so PostgreSQL accepts them as NULL)
records = [
    {k: (None if pd.isna(v) else v) for k, v in record.items()} 
    for record in df.to_dict(orient='records')
]

# 4. Connect and explicitly OVERWRITE the data
engine = get_engine()

with engine.begin() as conn:
    print("Fetching existing Pokédex numbers...")
    # Find out which Pokémon are already in the table
    existing = conn.execute(text("SELECT pokedex_number FROM videogame_pokedex_details WHERE pokedex_number IS NOT NULL")).fetchall()
    existing_pokedex_nums = {row[0] for row in existing}
    
    # Split the payload into records that need to be overwritten vs brand new records
    updates = [r for r in records if r['pokedex_number'] in existing_pokedex_nums]
    inserts = [r for r in records if r['pokedex_number'] not in existing_pokedex_nums]
    
    if updates:
        print(f"Overwriting {len(updates)} existing Pokémon...")
        
        # FIX: Added 'pokemon_name' to the exclusion list so we don't trigger the unique constraint
        update_cols = [k for k in updates[0].keys() if k not in ('pokedex_number', 'pokemon_id', 'pokemon_name', 'created_at', 'updated_at')]
        
        # Dynamically build the SET clause
        set_clause = ",\n".join([f"{col} = :{col}" for col in update_cols])
        
        # Explicitly force the updated_at column to trigger
        update_query = text(f"""
            UPDATE videogame_pokedex_details
            SET {set_clause},
                updated_at = CURRENT_TIMESTAMP
            WHERE pokedex_number = :pokedex_number
        """)
        
        # Execute bulk update
        conn.execute(update_query, updates)

    if inserts:
        print(f"Inserting {len(inserts)} new Pokémon...")
        insert_cols = [k for k in inserts[0].keys() if k not in ('pokemon_id', 'created_at', 'updated_at')]
        
        col_names = ", ".join(insert_cols)
        val_names = ", ".join([f":{col}" for col in insert_cols])
        
        insert_query = text(f"INSERT INTO videogame_pokedex_details ({col_names}) VALUES ({val_names})")
        
        # Execute bulk insert
        conn.execute(insert_query, inserts)

print("✅ Migration complete! Table completely overwritten while preserving pokemon_id and card connections.")