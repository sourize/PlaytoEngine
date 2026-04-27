# Playto Payout System

A production-grade payout engine demonstrating **money integrity**, **concurrency safety**, and **idempotency** using PostgreSQL, Django, Celery, and React.

## Stack

| Layer | Technology |
|-------|-----------|
| Database | PostgreSQL 15 (source of truth) |
| API | Django 4.2 + DRF |
| Background jobs | Celery 5.3 + Redis |
| Scheduled retries | Celery Beat |
| Dashboard | React 18 + Tailwind CSS + Vite |

## Quick Start

```bash
docker compose up --build
```

- **Dashboard**: http://localhost:3000
- **API**: http://localhost:8000/api/v1/

Docker automatically:
1. Starts PostgreSQL + Redis
2. Runs `migrate` + `seed` (3 test merchants with pre-loaded credits)
3. Starts Django, Celery worker (4 concurrent), and Celery beat (retry every 15s)
4. Starts React dashboard

## Run Tests

```bash
docker compose exec backend python manage.py test tests
```

## Verify Balance Invariant

```bash
docker compose exec backend python manage.py shell -c "
from merchants.models import Merchant, LedgerEntry
from django.db.models import Sum
for m in Merchant.objects.all():
    balance = m.ledger_entries.aggregate(t=Sum('amount_paise'))['t'] or 0
    print(f'{m.name}: {balance} paise ({balance/100:.2f} rupees)')
"
```

## API Reference

### Create Payout
```
POST /api/v1/payouts/
Headers: Idempotency-Key: <unique-key>
Body: { "merchant_id": 1, "amount_paise": 50000, "bank_account_id": "HDFC001" }
```

### List Merchants
```
GET /api/v1/merchants/
GET /api/v1/merchants/<id>/
```

### List Payouts
```
GET /api/v1/payouts/list/?merchant_id=1
GET /api/v1/payouts/<uuid>/
```

## Test Merchants (seeded)

| Name | Email | Balance |
|------|-------|---------|
| Rahul Freelance | rahul@example.com | ₹8,000 |
| Priya Design Studio | priya@example.com | ₹20,000 |
| Dev Solutions | dev@example.com | ₹10,000 |

## Architecture

See [EXPLAINER.md](./EXPLAINER.md) for a deep dive into the three hard problems: concurrency, idempotency, and state machine correctness.
