FROM python:3.11-slim

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .

# Strip Windows CRLF line endings — Git on Windows converts LF→CRLF,
# which breaks shell scripts running on Linux inside the container.
RUN sed -i 's/\r$//' start.sh

CMD ["gunicorn", "playto.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--timeout", "120"]
