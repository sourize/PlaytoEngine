FROM python:3.11-slim

WORKDIR /app

# Build context is repo root — paths prefixed with backend/
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .

CMD ["gunicorn", "playto.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--timeout", "120"]
