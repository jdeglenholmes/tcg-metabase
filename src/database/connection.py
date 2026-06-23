# Python/establish connections to PostgreSQL database

import os
from sqlalchemy import create_engine
from dotenv import load_dotenv

load_dotenv()

def get_engine():
    # 1. Try to grab the unified Supabase URL first (Recommended)
    db_url = os.getenv("DATABASE_URL")
    
    # 2. Fallback: Assemble from components if DATABASE_URL isn't set
    if not db_url:
        db_user = os.getenv("POSTGRES_USER")
        db_pass = os.getenv("POSTGRES_PASSWORD")
        db_name = os.getenv("POSTGRES_DB")
        # Pull the host and port dynamically instead of hardcoding "poke_db"
        host = os.getenv("POSTGRES_HOST", "aws-1-eu-central-1.pooler.supabase.com") 
        port = os.getenv("POSTGRES_PORT", "5432")
        
        db_url = f"postgresql://{db_user}:{db_pass}@{host}:{port}/{db_name}"
    
    # Pass connection arguments to the DB driver to explicitly suppress
    # HINT, DETAIL, and NOTICE messages (like the collation mismatch logs)
    return create_engine(
        db_url,
        connect_args={
            "options": "-c client_min_messages=warning"
        }
    )