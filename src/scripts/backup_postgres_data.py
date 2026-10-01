import os
import json
import sys
import subprocess
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, date
from uuid import UUID
from dotenv import load_dotenv
import logging

# --- LOGGING SETUP ---
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(message)s')
logger = logging.getLogger('DB_Backup')

def json_serial(obj):
    """JSON serializer for objects not serializable by default json code."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, UUID):
        return str(obj)
    raise TypeError(f"Type {type(obj)} not serializable")

def unified_backup():
    # 1. Load Environment Variables
    load_dotenv()
    db_uri = os.getenv("DATABASE_URL")
    
    if not db_uri:
        logger.error("❌ DATABASE_URL not found in environment variables.")
        sys.exit(1)
        return

    # 2. Setup Directories and Filenames
    backup_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../backups'))
    os.makedirs(backup_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    pg_dump_file = os.path.join(backup_dir, f"tcg_db_{timestamp}.dump")
    json_dump_file = os.path.join(backup_dir, "backup.json")

    # --- PART 1: COMPRESSED PG_DUMP (For Disaster Recovery) ---
    logger.info(f"🔄 Starting pg_dump backup to {pg_dump_file}...")
    command = [
        "pg_dump",
        db_uri,
        "-F", "c",
        "-f", pg_dump_file,
        "--no-owner",
        "--no-privileges"
    ]
    
    try:
        subprocess.run(command, check=True)
        size_mb = os.path.getsize(pg_dump_file) / (1024 * 1024)
        logger.info(f"✅ pg_dump completed! File size: {size_mb:.2f} MB")
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ pg_dump failed: {e}")
        sys.exit(1)
    except FileNotFoundError:
        logger.error("❌ 'pg_dump' command not found. Ensure PostgreSQL tools are installed.")
        sys.exit(1) 

    # --- PART 2: JSON DUMP (For Git Version Control & Diffs) ---
    logger.info(f"🔄 Starting JSON data extraction to {json_dump_file}...")
    try:
        conn = psycopg2.connect(db_uri)
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
        """)
        tables = [row['table_name'] for row in cursor.fetchall()]
        
        database_dump = {}
        for table in tables:
            cursor.execute(f'SELECT * FROM public."{table}"')
            database_dump[table] = cursor.fetchall()
            
        with open(json_dump_file, 'w') as json_file:
            json.dump(database_dump, json_file, default=json_serial, indent=4)
            
        cursor.close()
        conn.close()
        logger.info(f"✅ JSON dump completed successfully!")
        
    except Exception as e:
        logger.error(f"❌ JSON dump failed: {e}")
        sys.exit(1)
        
if __name__ == "__main__":
    unified_backup()