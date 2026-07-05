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
        host = os.getenv("POSTGRES_HOST", "aws-1-eu-central-1.pooler.supabase.com") 
        port = os.getenv("POSTGRES_PORT", "5432")
        db_url = f"postgresql://{db_user}:{db_pass}@{host}:{port}/{db_name}"
    
    # Universal Pool Safety Limits for Supabase Session Mode
    return create_engine(
        db_url,
        pool_size=5,          # Never hold more than 5 connections
        max_overflow=5,       # Allow up to 5 extra during traffic spikes (Max 10 total)
        pool_timeout=30,      # Give up after 30 seconds if pool is full
        pool_recycle=1800,    # Refresh connections every 30 mins
        pool_pre_ping=True,   # Auto-reconnect if Supabase drops the connection
        connect_args={
            "options": "-c client_min_messages=warning"
        }
    )