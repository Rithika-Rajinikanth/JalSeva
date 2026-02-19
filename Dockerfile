FROM python:3.11-slim

WORKDIR /app

# System dependencies for psycopg2 and python-magic
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Initialize DB on startup
CMD ["sh", "-c", "python -m app.core.init_db && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
