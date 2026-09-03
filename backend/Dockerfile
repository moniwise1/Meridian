FROM python:3.12-slim

WORKDIR /app

# System deps for psycopg2 (Postgres) and pymssql (SQL Server) - both need
# to compile/link against native libraries.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev freetds-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Metadata DB and generated-file directories - mount these as volumes in
# production so they survive a container restart (see docker-compose.yml).
RUN mkdir -p /app/data /app/artifacts /app/documents
ENV METADATA_DB_URL=sqlite:////app/data/metadata.db
ENV ARTIFACTS_DIR=/app/artifacts
ENV DOCUMENTS_DIR=/app/documents

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
