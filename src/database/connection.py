# Python/establish connections to PostgreSQL database

import os
from sqlalchemy import create_engine
from dotenv import load_dotenv

load_dotenv()

def get_engine():
    # Access credentials inside .env
    db_user = os.getenv("POSTGRES_USER")
    db_pass = os.getenv("POSTGRES_PASSWORD")
    db_name = os.getenv("POSTGRES_DB")

    # Check if we are running inside a Docker container
    if os.path.exists('/.dockerenv'):
        host = "poke_db"
        port = "5432"
    else:
        host = "localhost"
        port = "5433" # The port we mapped in docker-compose.yml

    db_url = f"postgresql://{db_user}:{db_pass}@{host}:{port}/{db_name}"
    return create_engine(db_url)