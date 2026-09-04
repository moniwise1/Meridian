FROM python:3.12-slim

WORKDIR /app

# System deps: gcc/libpq-dev/freetds-dev for psycopg2 (Postgres) and
# pymssql (SQL Server), which need to compile/link against native
# libraries; tesseract-ocr is the actual OCR engine binary
# app/agents/document_intelligence.py's OCR fallback shells out to via
# pytesseract - that's a thin Python wrapper, not the engine itself, so
# it needs this system package present or every scanned-page OCR attempt
# fails open to "no text extracted" (see that module's docstring).
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev freetds-dev tesseract-ocr \
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
# Shell form (not exec-array) so ${PORT} actually expands - platforms like
# Railway assign a container's public port at runtime via $PORT and route
# traffic to whatever that is, not necessarily 8000; falls back to 8000 for
# plain `docker run`/docker-compose where nothing sets $PORT.
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
