import os
import sys
import logging
from sqlalchemy import text

# Ensure project root is in path
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from src.database.connection import get_engine

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(message)s')
logger = logging.getLogger('Mart_Refresh')

def refresh_all_marts():
    engine = get_engine()
    
    # Order matters if views depend on each other during refresh
    marts = [
        "analytics.mart_card_metrics",
        "analytics.mart_card_economics",
        "analytics.mart_network_edges",
        "analytics.mart_lore_connections",
    ]
    
    logger.info("🚀 Starting Materialized View Refresh...")
    
    # Materialized View Refreshes cannot run inside an explicit multi-statement transaction block in some Postgres configurations,
    # so we execute them using autocommit / isolated connections.
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        for mart in marts:
            try:
                logger.info(f"   ↳ Refreshing {mart}...")
                conn.execute(text(f"REFRESH MATERIALIZED VIEW {mart};"))
                logger.info(f"   ✓ {mart} refreshed successfully.")
            except Exception as e:
                logger.error(f"   ❌ Failed to refresh {mart}: {e}")

    logger.info("🎉 All Gold Marts are up to date!")

if __name__ == '__main__':
    refresh_all_marts()