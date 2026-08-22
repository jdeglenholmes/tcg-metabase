import os
import subprocess
from datetime import datetime
from dotenv import load_dotenv
import logging

# --- LOGGING SETUP ---
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(message)s')
logger = logging.getLogger('DB_Backup')

def create_local_backup():
    # 1. Load your Supabase DB URI from your .env file
    # Example format: postgresql://postgres.[project_ref]:[password]@aws-0-[region].pooler.supabase.com:6543/postgres
    load_dotenv()
    db_uri = os.getenv("DATABASE_URL")
    
    if not db_uri:
        logger.error("❌ DATABASE_URL not found in environment variables.")
        return

    # 2. Define the backup directory
    backup_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../backups'))
    os.makedirs(backup_dir, exist_ok=True)
    
    # 3. Generate a timestamped filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = os.path.join(backup_dir, f"tcg_wiki_backup_{timestamp}.dump")
    
    logger.info(f"🔄 Starting database backup to {backup_file}...")
    
    # 4. Construct the pg_dump command
    # -F c: Custom format (compressed, required for pg_restore)
    # --no-owner: Prevents role/permission conflicts if you restore to a different environment
    command = [
        "pg_dump",
        db_uri,
        "-F", "c",
        "-f", backup_file,
        "--no-owner",
        "--no-privileges"
    ]
    
    # 5. Execute the backup
    try:
        subprocess.run(command, check=True)
        logger.info(f"✅ Backup completed successfully! File size: {os.path.getsize(backup_file) / (1024*1024):.2f} MB")
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ Backup failed: {e}")
    except FileNotFoundError:
         logger.error("❌ 'pg_dump' command not found. Ensure PostgreSQL tools are installed and in your system PATH.")

if __name__ == "__main__":
    create_local_backup()