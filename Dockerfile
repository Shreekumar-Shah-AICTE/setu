# Optional Dockerfile — the default SETU demo needs no Docker.
FROM python:3.11-slim

WORKDIR /app

# psycopg2-binary is added here so the image can talk to PostgreSQL.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt psycopg2-binary

COPY . .

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
