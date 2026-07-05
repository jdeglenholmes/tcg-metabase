# Python/establish connections to PostgreSQL database

import os
from sqlalchemy import create_engine
from dotenv import load_dotenv

load_dotenv()

def get_engine():
    db_url = os.getenv("DATABASE_URL")
    
    if not db_url:
        db_user = os.getenv("POSTGRES_USER")
        db_pass = os.getenv("POSTGRES_PASSWORD")
        db_name = os.getenv("POSTGRES_DB")
        host = os.getenv("POSTGRES_HOST", "aws-1-eu-central-1.pooler.supabase.com") 
        
        # --- THE FIX: Use Port 6543 for Transaction Mode ---
        port = os.getenv("POSTGRES_PORT", "6543") 
        
        db_url = f"postgresql://{db_user}:{db_pass}@{host}:{port}/{db_name}"
    
    return create_engine(
        db_url,
        pool_size=5,          
        max_overflow=5,       
        pool_timeout=30,      
        pool_recycle=1800,    
        pool_pre_ping=True,   
        connect_args={
            "options": "-c client_min_messages=warning"
        }
    )