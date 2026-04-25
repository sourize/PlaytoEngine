#!/bin/sh
set -e

echo "==> Running migrations..."
python manage.py makemigrations merchants payouts
python manage.py migrate

echo "==> Seeding data..."
python manage.py seed

echo "==> Starting Celery worker in background..."
celery -A playto worker --loglevel=info --concurrency=2 &

echo "==> Starting Celery beat in background..."
celery -A playto beat --loglevel=info &

echo "==> Starting Gunicorn..."
exec gunicorn playto.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers 2 --timeout 120
