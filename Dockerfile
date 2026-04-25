FROM python:3.11-slim

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .

# Strip Windows CRLF line endings so start.sh runs cleanly on Linux
RUN sed -i 's/\r$//' start.sh

# start.sh runs: migrate → seed → gunicorn on ${PORT:-8000}
# Railway overrides this per-service via dashboard Start Command
CMD ["sh", "start.sh"]
