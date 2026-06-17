# Dockerfile/initialise container with specific tools

# 1. Use a slim Python image to keep the size down
FROM python:3.12-slim

# 2. Set the working directory inside the container
WORKDIR /app

# 3. Install system dependencies (needed for some Postgres libraries)
RUN apt-get update && apt-get install -y \
    git \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# 4. Copy requirements and install them
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. Copy the rest of your code
# We copy everything into /app so internal imports like 'src.database' work
COPY . .

# 6. Default command (this can be overridden by docker-compose)
CMD ["python", "main.py"]