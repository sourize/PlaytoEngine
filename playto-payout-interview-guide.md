# Playto Payout — Interview Preparation Guide

> **How to use this document:** Read top-to-bottom once to build the mental model, then use the headings as a quick-reference index during an interview. Every "Why not X?" and "What if Y?" question an interviewer might ask is answered inline.

---

## 1. Project Overview

### What it does

Playto Payout is a **merchant payout engine** — the backend system that takes money sitting in a merchant's account and moves it to their bank. Think of it as the "send money out" half of a payments platform.

When a freelancer completes a project on Playto, a customer's payment sits in the platform. The freelancer (merchant) then requests a payout: "send my ₹5,000 to my HDFC account." This system handles that request safely, even when hundreds of merchants are requesting payouts at the same time.

### The analogy

Imagine a bank teller with a ledger book. Every time money comes in, they write a positive entry. Every time money goes out, they write a negative entry. The balance is never written down — it's always calculated by adding up all the entries. If two customers rush to the window at the same time trying to withdraw more than what's in the account, the teller only serves one at a time (the lock), so the math always stays correct.

This project is that teller, implemented in software.

### The three hard problems it solves

| Problem | Risk if unsolved | Solution used |
|---------|-----------------|---------------|
| **Concurrency** | Two simultaneous payouts both pass the balance check, causing overdraft | `SELECT FOR UPDATE` — PostgreSQL row lock on the merchant |
| **Idempotency** | Network retry creates a duplicate payout, double-charging the merchant | Double-check pattern + DB unique constraint |
| **State integrity** | A bug moves a completed payout back to pending, causing double payment | Explicit `transition_to()` state machine with `VALID_TRANSITIONS` dict |

### Technology stack

| Layer | Technology | Why |
|-------|-----------|-----|
| Database | **PostgreSQL 15** | Row-level locking (`SELECT FOR UPDATE`), ACID transactions |
| API | **Django 4.2 + DRF** | Mature ORM with transaction support |
| Task queue | **Celery 5.3** | Async background processing, beat scheduler |
| Message broker | **Redis 7** | Celery's transport layer |
| Frontend | **React 18 + Tailwind + Vite** | Live-polling dashboard |
| Containers | **Docker Compose** | Single-command local setup |

---

## 2. Core Design Principle: The Ledger Model

Before diving into individual files, understand this invariant — **everything else follows from it.**

**Balance is never stored. It is always derived:**

```python
SELECT SUM(amount_paise) FROM merchants_ledgerentry WHERE merchant_id = ?
```

Every rupee that moves through the system creates a ledger entry. The balance at any point in time is the sum of all those entries. This is called a **double-entry bookkeeping** approach.

### Why not just store `merchant.balance` as a column?

If balance were a stored integer, every payout would require:
1. Read `merchant.balance` into Python
2. Subtract the amount in Python
3. Write the new value back

Under concurrency, two requests read the same value, both subtract, both write back — **double spend**. The read and write are not atomic.

With the ledger approach, the balance check (`SUM`) and the debit write (`INSERT`) happen inside the same locked database transaction — they are physically atomic.

### Entry types (signed integers)

| Type | Sign | When created |
|------|------|-------------|
| `credit` | **positive** | Customer payment received |
| `debit_hold` | **negative** | Payout requested — funds reserved |
| `debit_release` | **positive** | Payout failed — funds returned |

---

## 3. File-by-File Breakdown

---

### `backend/merchants/models.py`

**Role:** Defines the two most fundamental data structures in the system: `Merchant` and `LedgerEntry`.

#### `Merchant` model

A merchant has three fields: `name`, `email`, `created_at`. Notably, **no balance field** — balance is computed on demand.

**`get_balance()`**
```python
def get_balance(self):
    result = self.ledger_entries.aggregate(total=Sum('amount_paise'))
    return result['total'] or 0
```
Issues a single `SELECT SUM(amount_paise) ...` query. The `or 0` handles the edge case where no entries exist yet (aggregate returns `None`). This is the **balance invariant** — always call this instead of tracking balance separately.

**`get_held_balance()`**
```python
def get_held_balance(self):
    from payouts.models import Payout
    result = self.payouts.filter(
        status__in=[Payout.PENDING, Payout.PROCESSING]
    ).aggregate(total=Sum('amount_paise'))
    return result['total'] or 0
```
Sums the amounts of payouts that are currently in-flight (not yet settled). This is for **display only** — it tells the merchant "₹500 is currently being processed." It does not affect the actual available balance calculation (that comes from `get_balance()`).

> **Interview Q: Why the circular import `from payouts.models import Payout` inside the method?**
> Django has two apps: `merchants` and `payouts`. `Payout` has a FK to `Merchant`. If we imported `Payout` at the top of `merchants/models.py`, Python would see a circular dependency (`merchants → payouts → merchants`). Deferring the import inside the method body breaks the cycle — it runs at call time, not import time.

#### `LedgerEntry` model

```python
amount_paise = models.BigIntegerField()
```

**Why `BigIntegerField` and not `DecimalField`?** Floating-point (`FloatField`) and even `DecimalField` can accumulate rounding errors over millions of operations. Storing paise (1 rupee = 100 paise) as an exact integer means all arithmetic is perfectly precise. ₹1.50 = 150 paise, no fractions, no rounding.

The `payout` FK is nullable — credit entries (money coming in) don't relate to any payout, only `debit_hold` and `debit_release` entries do.

`class Meta: ordering = ['-created_at']` ensures ledger entries always come back newest-first without needing to specify ordering in every query.

---

### `backend/payouts/models.py`

**Role:** Defines the `Payout` model and its state machine.

#### The state machine

```python
VALID_TRANSITIONS = {
    PENDING:    [PROCESSING],
    PROCESSING: [COMPLETED, FAILED],
    COMPLETED:  [],   # Terminal — no outgoing transitions
    FAILED:     [],   # Terminal — no outgoing transitions
}
```

Visually:
```
PENDING ──► PROCESSING ──► COMPLETED
                      └──► FAILED
```

**`transition_to(new_status)`**
```python
def transition_to(self, new_status):
    allowed = self.VALID_TRANSITIONS.get(self.status, [])
    if new_status not in allowed:
        raise ValueError(f"Illegal transition: {self.status} → {new_status}")
    self.status = new_status
```

This is the **only sanctioned way to change status.** Setting `payout.status = 'completed'` directly bypasses the guard. By convention, all code uses `transition_to()`. The method raises `ValueError` for illegal moves — e.g., `completed → pending` would be a double-payout bug.

> **Interview Q: Why are `COMPLETED` and `FAILED` terminal?**
> A completed payout means money has already left the platform and reached the bank. Allowing any transition out of `COMPLETED` could cause the payout task to re-run and send the money again. `FAILED` is terminal because fund recovery (via `DEBIT_RELEASE`) happens atomically at the moment of failure — there's nothing to retry.

#### Key fields

- **`id = UUIDField`** — UUID primary key instead of auto-increment integer. UUIDs are safe to expose in URLs (no sequential enumeration attack) and work well in distributed systems.
- **`idempotency_key`** — Client-supplied string scoped per merchant. The DB enforces `unique_together = [['merchant', 'idempotency_key']]` as a last-resort duplicate guard.
- **`attempt_count`** — Tracks how many times `process_payout` has been called for this payout. Used by the retry beat task to enforce the 3-attempt maximum.
- **`processing_started_at`** — Timestamp of when processing began. The beat task uses this to detect "hung" payouts (PROCESSING for too long).

---

### `backend/payouts/views.py` — `PayoutCreateView`

**Role:** The most critical file in the project. Handles the `POST /api/v1/payouts/` endpoint with concurrent safety and idempotency.

#### Full flow, step by step

**Step 1: Validate inputs**
```python
idempotency_key = request.headers.get('Idempotency-Key', '').strip()
```
The `Idempotency-Key` header is required. Clients generate a UUID per request attempt. If rejected, they can retry with the same key.

**Step 2: Fast-path idempotency check (no lock)**
```python
existing = Payout.objects.filter(
    merchant_id=merchant_id,
    idempotency_key=idempotency_key,
    created_at__gte=key_expiry,   # 24-hour TTL
).first()
if existing:
    return Response(PayoutSerializer(existing).data, status=200)
```
A read-only check before acquiring any lock. If this key has been seen in the last 24 hours, return the cached payout immediately — no database write, no lock. This is the **common case** for retries.

**Step 3: Acquire the lock**
```python
with transaction.atomic():
    merchant = Merchant.objects.select_for_update().get(id=merchant_id)
```
`SELECT FOR UPDATE` issues a PostgreSQL row-level exclusive lock on the merchant row. Any other transaction trying to lock the same merchant **blocks at the database level** until this transaction commits or rolls back. This is the concurrency primitive.

> **Interview Q: Why lock the merchant row instead of something more granular?**
> We need to serialize all payout requests for a given merchant so that balance checks and debits are atomic. The merchant row is the natural per-merchant mutex. Locking a separate "balance" row would work too, but the merchant row already exists and represents the entity we're protecting.

**Step 4: Second idempotency check (inside the lock)**
```python
existing = Payout.objects.filter(
    merchant=merchant,
    idempotency_key=idempotency_key,
    created_at__gte=key_expiry,
).first()
if existing:
    return Response(PayoutSerializer(existing).data, status=200)
```
Handles the race condition where two requests with the **same key** arrive simultaneously. Both pass Step 2 (key doesn't exist yet). The first acquires the lock, creates the payout, commits. The second acquires the lock and finds the payout here.

**Step 5: Balance check inside the lock**
```python
balance = LedgerEntry.objects.filter(
    merchant=merchant
).aggregate(total=Sum('amount_paise'))['total'] or 0

if balance < amount_paise:
    return Response({'error': 'Insufficient balance...'}, status=400)
```

> **The critical detail:** This `SUM()` runs inside `transaction.atomic()` with the merchant row locked. No other transaction can insert a `DEBIT_HOLD` for this merchant while we're here. The read and the subsequent write (Step 6) are atomic.

**Step 6: Create payout and hold funds atomically**
```python
payout = Payout.objects.create(...)

LedgerEntry.objects.create(
    merchant=merchant,
    amount_paise=-amount_paise,   # NEGATIVE — reduces balance
    entry_type=LedgerEntry.DEBIT_HOLD,
    payout=payout,
)
```
Both `INSERT`s happen in the same atomic transaction. If either fails, both roll back. The merchant is never in a state where a payout exists but funds aren't held (or vice versa).

**Step 7: Dispatch Celery task AFTER commit**
```python
# Outside the with transaction.atomic() block
process_payout.delay(str(payout.id))
```

> **Why outside the transaction?** If we called `.delay()` inside `transaction.atomic()`, the Celery worker could pick up the task before the database transaction commits (they run concurrently). The worker would query for the payout, find nothing (not committed yet), and exit silently. Dispatching after the `with` block guarantees the row is visible before the worker starts.

**Step 8: IntegrityError fallback**
```python
except IntegrityError:
    existing = Payout.objects.filter(...).first()
    if existing:
        return Response(PayoutSerializer(existing).data, status=200)
```
The `unique_together` constraint on `(merchant, idempotency_key)` is the last line of defense. If two identical requests somehow slip through both idempotency checks (theoretically impossible but defensively correct), the DB raises `IntegrityError`, which returns the existing payout as a 200.

---

### `backend/payouts/tasks.py`

**Role:** Two Celery tasks — one that processes individual payouts, one that rescues stuck ones.

#### `process_payout(payout_id)`

This task runs asynchronously in a Celery worker process, separate from the web server.

**Phase 1: PENDING → PROCESSING (inside a transaction)**
```python
with transaction.atomic():
    payout = Payout.objects.select_for_update().get(id=payout_id)
    if payout.status != Payout.PENDING:
        return   # Already handled — idempotent exit
    payout.transition_to(Payout.PROCESSING)
    payout.processing_started_at = timezone.now()
    payout.attempt_count += 1
    payout.save()
```
Re-locks the payout with `select_for_update()`. The status guard (`if payout.status != Payout.PENDING`) makes this phase idempotent — if the task runs twice (e.g., Celery retried), the second run exits cleanly.

**Phase 2: Simulate bank API call (outside any transaction)**
```python
outcome = random.choices(
    ['success', 'failure', 'hung'],
    weights=[70, 20, 10]
)[0]
```
The bank call happens outside a transaction. Holding a database transaction open during a network call is dangerous — it blocks other transactions waiting on locks, and connections are a finite resource.

Outcomes: 70% success, 20% failure, 10% hung (task exits without finalizing).

**Phase 3: Finalize (inside a second transaction)**
```python
with transaction.atomic():
    payout = Payout.objects.select_for_update().get(id=payout_id)
    if payout.status != Payout.PROCESSING:
        return   # Beat task already handled this payout
```
Re-fetches with a lock. The status guard handles the race where the beat task timed out and reset/failed the payout while Phase 2 was running.

On **failure**, funds are returned atomically:
```python
payout.transition_to(Payout.FAILED)
payout.save()
LedgerEntry.objects.create(
    merchant=payout.merchant,
    amount_paise=payout.amount_paise,   # POSITIVE — restores balance
    entry_type=LedgerEntry.DEBIT_RELEASE,
    ...
)
```
The status change and the ledger entry are in the same transaction. If the `INSERT` fails, the status update rolls back too. The merchant can never be in a state where `status=FAILED` but funds aren't returned.

#### `retry_stuck_payouts()`

Runs every **15 seconds** via Celery Beat. Finds payouts that have been in `PROCESSING` for longer than their backoff threshold.

**Exponential backoff calculation:**
```python
backoff_seconds = 30 * (2 ** (payout.attempt_count - 1))
# attempt 1 → 30s, attempt 2 → 60s, attempt 3 → 120s
```

**Decision logic (inside a lock):**
- If `attempt_count >= 3`: permanently fail and return funds
- Otherwise: reset to `PENDING`, dispatch `process_payout.delay()` again

> **Why bypass `transition_to()` when resetting to PENDING?**
> `VALID_TRANSITIONS[PROCESSING]` only allows `COMPLETED` or `FAILED`. Resetting to `PENDING` for retry is intentional and documented — it's the one place where we directly set `p.status = Payout.PENDING` without the state machine, because the state machine's job is to prevent accidental terminal-state escapes, not to prevent legitimate retry logic.

---

### `backend/merchants/serializers.py`

**Role:** Converts `Merchant` and `LedgerEntry` model instances to JSON for API responses.

`MerchantSerializer` uses `SerializerMethodField` for three computed properties:

```python
available_balance = serializers.SerializerMethodField()
held_balance = serializers.SerializerMethodField()
recent_entries = serializers.SerializerMethodField()
```

These call `obj.get_balance()`, `obj.get_held_balance()`, and fetch the 20 most recent ledger entries respectively. This means every `GET /api/v1/merchants/<id>/` runs **three queries**: one for balance SUM, one for held balance SUM, one for recent entries.

---

### `backend/merchants/management/commands/seed.py`

**Role:** A Django management command that populates the database with test data on first run.

Uses `get_or_create()` to be idempotent — running `seed` twice doesn't duplicate data. Seeds three merchants: Rahul Freelance (₹8,000), Priya Design Studio (₹20,000), and Dev Solutions (₹10,000).

Called automatically in `docker-compose.yml`:
```yaml
command: sh -c "python manage.py makemigrations merchants payouts &&
                python manage.py migrate &&
                python manage.py seed &&
                python manage.py runserver 0.0.0.0:8000"
```

---

### `backend/tests/test_concurrency.py`

**Role:** Proves that `SELECT FOR UPDATE` prevents overdraft under simultaneous requests.

**Why `TransactionTestCase` instead of `TestCase`?**

Django's `TestCase` wraps the entire test in a transaction that's rolled back at the end. But `SELECT FOR UPDATE` inside a nested transaction doesn't block the same way — threads share the same outer transaction boundary. `TransactionTestCase` uses real transaction commits and truncates tables after each test (slower, but necessary to test real locking behavior).

**What the test proves:**
```python
# 10,000 paise balance, two threads each requesting 6,000 paise
t1 = threading.Thread(target=request_payout, args=('key-1',))
t2 = threading.Thread(target=request_payout, args=('key-2',))
t1.start(); t2.start()
t1.join(); t2.join()

# Exactly one 201, exactly one 400
self.assertEqual(results.count(201), 1)
self.assertEqual(results.count(400), 1)
# Balance invariant: 10,000 - 6,000 = 4,000
self.assertEqual(self.merchant.get_balance(), 4_000)
```

This test **fails reliably** if you remove `select_for_update()` — both threads pass the balance check and both create payouts, resulting in two 201s and a negative balance.

---

### `backend/tests/test_idempotency.py`

**Role:** Proves that repeated requests with the same key produce one payout, not multiple.

**Three test cases:**

1. **`test_same_key_returns_same_payout`** — First call returns 201, second call with same key returns 200 with identical payout ID. Only one `DEBIT_HOLD` entry created.

2. **`test_different_keys_create_different_payouts`** — Two different keys create two separate payouts, both return 201.

3. **`test_expired_key_allows_new_payout`** — Creates a payout with a key, backdates it 25 hours, sends a new request with the same key — should create a new payout (201) with a different UUID, because the old key has expired.

---

### `backend/playto/celery.py`

**Role:** Instantiates the Celery application and connects it to Django settings.

```python
app = Celery('playto')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()
```

`autodiscover_tasks()` scans all `INSTALLED_APPS` for a `tasks.py` file and registers the tasks automatically. This is why `payouts/tasks.py` doesn't need to be manually registered.

---

### `backend/playto/__init__.py`

```python
from .celery import app as celery_app
__all__ = ('celery_app',)
```

This line makes the Celery app load when Django starts, so the beat scheduler and worker can find tasks. Without it, `python manage.py` commands wouldn't initialize Celery.

---

### `frontend/src/components/Dashboard.jsx`

**Role:** The main dashboard component. Fetches merchant data and payout history, auto-refreshes every 5 seconds.

```javascript
useEffect(() => {
    refresh()
    const interval = setInterval(refresh, 5000)
    return () => clearInterval(interval)   // cleanup on unmount
}, [refresh])
```

This is **polling** — not WebSockets. The `5000ms` interval means the dashboard always shows data at most 5 seconds stale. `clearInterval` in the cleanup function prevents memory leaks when switching between merchants.

The `refresh` function is wrapped in `useCallback` with `[merchant.id]` dependency — it only recreates when the merchant changes, preventing the `useEffect` from re-running unnecessarily.

---

### `frontend/src/components/PayoutForm.jsx`

**Role:** The payout submission form. Generates a new idempotency key per submission.

```javascript
function generateKey() {
    return crypto.randomUUID()   // Browser built-in, no library needed
}

async function handleSubmit() {
    const payout = await createPayout({
        ...
        idempotencyKey: generateKey(),   // Fresh UUID every click
    })
}
```

A new UUID is generated on every button click — this is correct behavior. The idempotency key is per-request-attempt, not per-merchant or per-session. If the submission fails at the network level and the user clicks again, a new key creates a new payout (which is the intended behavior — they want to retry the request).

---

### `frontend/src/api.js`

**Role:** Thin wrapper over `fetch` for all API calls. All requests go to `/api/v1/*`, which Vite proxies to the backend container.

```javascript
// vite.config.js proxy:
'/api': { target: 'http://backend:8000', changeOrigin: true }
```

This means the frontend doesn't need to know the backend's hostname — it just calls `/api/v1/...` and Vite forwards the request. This avoids CORS issues in development (same origin from the browser's perspective).

---

## 4. Overall Architecture

### How all components connect

```
Browser (React, port 3000)
    │
    │ /api/v1/* (proxied by Vite)
    ▼
Django API (port 8000)
    │                    │
    │ SELECT FOR UPDATE  │ .delay()
    ▼                    ▼
PostgreSQL ◄────── Celery Worker ◄── Redis (task queue) ◄── Celery Beat
(source of truth)                                            (scheduler)
```

### Data flow for a payout request

```
1. Browser → POST /api/v1/payouts/ + Idempotency-Key header
2. Django validates inputs
3. Django checks idempotency (fast path, no lock)
4. Django opens transaction, locks merchant row
5. Django checks idempotency again (inside lock)
6. Django computes balance via SUM(ledger_entries)
7. If sufficient: creates Payout + DEBIT_HOLD entry
8. Transaction commits, lock released
9. Django dispatches process_payout.delay(payout_id) to Redis
10. Celery worker picks up task from Redis
11. Worker transitions PENDING → PROCESSING (locked)
12. Worker simulates bank API call
13. Worker transitions PROCESSING → COMPLETED or FAILED (locked)
14. On FAILED: worker creates DEBIT_RELEASE entry (same transaction)
15. Every 15s: Beat sends retry_stuck_payouts to worker
16. React polls GET /api/v1/merchants/<id>/ every 5s, shows updated state
```

### Key design decisions and why

**1. Why PostgreSQL and not NoSQL?**
This system needs ACID transactions and row-level locking. NoSQL databases don't provide these guarantees. Money integrity requires the database to enforce atomicity — if two writes must happen together (payout + ledger entry), the database must guarantee that either both happen or neither does.

**2. Why Celery and not Django async views?**
The bank API call (simulated here) takes time and has uncertain duration. We don't want to hold a web server thread open waiting for it. Celery moves the work to a separate process pool, freeing the web server to handle new requests immediately.

**3. Why Redis as the broker?**
Redis is fast, simple, and sufficient for a task queue. The tasks here are small JSON messages (just a payout UUID). The real data lives in PostgreSQL — Redis only stores "which tasks are queued."

**4. Why not use Django Channels / WebSockets for live updates?**
Polling every 5 seconds is simpler to implement, easier to debug, and sufficient for this use case. Payout resolution takes seconds, so 5-second polling gives a good enough user experience without the complexity of a WebSocket connection.

**5. Why UUID primary key for Payout?**
- Non-guessable (no sequential enumeration attack: `/payouts/1`, `/payouts/2`, ...)
- Safe to pass in URLs and Celery task arguments
- Works in distributed systems where multiple nodes might create records simultaneously

---

## 5. Common Interview Questions

**Q: What happens if the Celery worker crashes after writing PENDING but before calling `process_payout.delay()`?**

A: The payout stays in `PENDING` forever. The `retry_stuck_payouts` beat task only looks for `PROCESSING` payouts. A production fix would be to also scan for `PENDING` payouts older than N minutes and requeue them.

**Q: What happens if PostgreSQL goes down mid-transaction?**

A: PostgreSQL rolls back uncommitted transactions automatically on recovery. If the connection dies after the `Payout` INSERT but before the `LedgerEntry` INSERT, both roll back — the merchant is neither charged nor has a payout record. Celery never received the task (dispatched after commit), so nothing is orphaned.

**Q: Could you have two `retry_stuck_payouts` beat tasks running simultaneously and double-retrying a payout?**

A: No. Each retry re-fetches with `select_for_update()`. The first instance acquires the lock and resets the payout to `PENDING`. When the second instance acquires the lock, `p.status != Payout.PROCESSING` — it hits the `continue` guard and skips.

**Q: The balance check uses `SUM()` over potentially millions of rows. Won't that be slow?**

A: In a real system, you'd add a materialized balance column updated via triggers, or a periodic snapshot table, keeping the ledger as the source of truth but avoiding full scans. For this project, a DB index on `(merchant_id)` makes the scan fast enough. The key point is correctness first; optimization is additive.

**Q: Why is `CELERY_BEAT_SCHEDULE` hardcoded in settings instead of using a database-backed scheduler?**

A: The database-backed scheduler (`django-celery-beat`) is more flexible (schedules editable at runtime) but adds complexity. A single hardcoded retry task with a fixed interval is sufficient here. In production, `django-celery-beat` would be the right choice.

**Q: What's the difference between `available_balance` and `held_balance` in the API response?**

A: `available_balance` = `SUM(all ledger entries)` — this is the true balance after deducting in-flight holds. `held_balance` = sum of amounts for `PENDING`/`PROCESSING` payouts — purely informational, shows "this much is currently being processed." The sum of both equals the merchant's gross balance (all money received, no debits yet).

---

## 6. Running the Project

```bash
cd playto-payout
docker compose up --build      # First run (builds images)
docker compose up              # Subsequent runs (uses cached images)
```

**Run tests:**
```bash
docker compose exec backend python manage.py test tests
```

**Verify balance invariant manually:**
```bash
docker compose exec backend python manage.py shell -c "
from merchants.models import Merchant
from django.db.models import Sum
for m in Merchant.objects.all():
    b = m.ledger_entries.aggregate(t=Sum('amount_paise'))['t'] or 0
    print(f'{m.name}: {b} paise ({b/100:.2f} rupees)')
"
```

**URLs when running:**
- Dashboard: http://localhost:3000
- API: http://localhost:8000/api/v1/merchants/
