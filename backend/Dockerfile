FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y libpq-dev gcc && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Default CMD — Render overrides this per-service via startCommand in render.yaml
CMD ["gunicorn", "playto.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--timeout", "120"]
