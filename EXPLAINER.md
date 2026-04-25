# Playto Payout — Engineering Explainer

This document explains the three hardest problems in building a payout system and exactly how this codebase solves them.

---

## 1. The Ledger Model — Why Balance Is Never Stored

Balance is a **derived value**, never a column. It is always computed as:

```sql
SELECT SUM(amount_paise) FROM merchants_ledgerentry WHERE merchant_id = ?
```

### Why this matters

If balance were a stored integer (`merchant.balance`), every payout would require:
1. Read `merchant.balance`
2. Subtract amount
3. Write `merchant.balance` back

This is a read-modify-write cycle. Under concurrency, two concurrent reads see the same balance, both subtract, and both write back — **double spend**.

### Entry types (all signed)

| Type | Sign | Meaning |
|------|------|---------|
| `credit` | positive | Customer paid merchant |
| `debit_hold` | **negative** | Payout initiated, funds reserved |
| `debit_release` | positive | Payout failed, funds restored |

A single `SUM()` across all signed entries is always the true balance. There is no way for the credit-sum and debit-sum to drift apart because there is only one sum.

### Why `BigIntegerField` not `DecimalField`

Floating-point and even `Decimal` can introduce rounding errors over millions of operations. Storing paise as integers means arithmetic is exact. `₹1.50 = 150 paise` — no fractions, no rounding.

---

## 2. Concurrency — SELECT FOR UPDATE as a Per-Merchant Mutex

### The Problem

Two API requests arrive simultaneously for the same merchant:
- Request A: Payout ₹600 (balance: ₹1,000)
- Request B: Payout ₹600 (balance: ₹1,000)

Without locking, both read balance = 1,000, both check `1000 >= 600 ✓`, both create payouts. Result: ₹1,200 debited from ₹1,000 balance. **Overdraft.**

### The Solution

```python
merchant = Merchant.objects.select_for_update().get(id=merchant_id)
```

This issues `SELECT ... FOR UPDATE` to PostgreSQL, which acquires a **row-level exclusive lock** on the merchant row. Any concurrent transaction attempting the same lock **blocks at the database level** — not Python, not Django — until the first transaction commits or rolls back.

This transforms "check-then-deduct" from a TOCTOU (time-of-check/time-of-use) race into a **serialized operation**:

```
Request A acquires lock  ──────────────────────────────────► commits
Request B blocks here ──────────────────────────────────────► sees updated balance ──► rejects
```

The balance check and ledger write happen **inside the same `transaction.atomic()` block**. The lock is released only when the transaction ends.

### What "wrong" looks like

AI-generated code commonly writes:
```python
# WRONG — fetches value into Python then subtracts
merchant.refresh_from_db()
if merchant.balance < amount_paise:  # race: another TX can debit between here...
    return error
# ...and here
LedgerEntry.objects.create(amount_paise=-amount_paise)
```

The problem: `refresh_from_db()` reads the balance into Python memory. Between that read and the ledger write, another transaction can debit the same balance. The check and the write are not atomic.

The correct version aggregates at the DB level **inside the same locked transaction**:
```python
balance = LedgerEntry.objects.filter(
    merchant=merchant
).aggregate(total=Sum('amount_paise'))['total'] or 0

if balance < amount_paise:
    return error

LedgerEntry.objects.create(amount_paise=-amount_paise, ...)
```

Both the `SUM()` and the `INSERT` happen within the same `SELECT FOR UPDATE` transaction. They are atomic.

---

## 3. Idempotency — The Double-Check Pattern

### The Problem

Network timeouts cause clients to retry. A retry that creates a duplicate payout double-charges the merchant.

### The Solution: Two Checks

**Check 1 (fast path, no lock):**
```python
existing = Payout.objects.filter(
    merchant_id=merchant_id,
    idempotency_key=idempotency_key,
    created_at__gte=key_expiry,
).first()
if existing:
    return Response(PayoutSerializer(existing).data, status=200)
```

If we've seen this key before (within 24h), return the cached response immediately. No lock needed — it's a read.

**Check 2 (inside the lock):**
```python
with transaction.atomic():
    merchant = Merchant.objects.select_for_update().get(...)

    existing = Payout.objects.filter(
        merchant=merchant,
        idempotency_key=idempotency_key,
        created_at__gte=key_expiry,
    ).first()
    if existing:
        return Response(PayoutSerializer(existing).data, status=200)
```

This handles the race: two requests with the **same key** arrive simultaneously. Both pass Check 1 (key not found yet). The first acquires the lock and creates the payout. The second acquires the lock after the first commits and finds the payout in Check 2.

**Last resort — DB constraint:**
```python
# In Payout.Meta:
unique_together = [['merchant', 'idempotency_key']]
```

If both requests somehow slip through both checks (theoretically impossible but defensively correct), the database raises `IntegrityError`, which the view catches and converts to a 200 response.

### The TTL

Idempotency keys expire after 24 hours. After expiry, a request with the same key creates a new payout. This is intentional — it allows merchants to safely reuse keys across billing cycles.

---

## 4. The State Machine — transition_to()

Payout status is a finite state machine:

```
PENDING ──► PROCESSING ──► COMPLETED
                      └──► FAILED
```

`COMPLETED` and `FAILED` are terminal — no outgoing transitions.

```python
VALID_TRANSITIONS = {
    PENDING: [PROCESSING],
    PROCESSING: [COMPLETED, FAILED],
    COMPLETED: [],   # Terminal
    FAILED: [],      # Terminal
}

def transition_to(self, new_status):
    allowed = self.VALID_TRANSITIONS.get(self.status, [])
    if new_status not in allowed:
        raise ValueError(f"Illegal transition: {self.status} → {new_status}")
    self.status = new_status
```

`transition_to()` is the **only** way to change status. Setting `payout.status = 'completed'` directly bypasses the guard — convention in this codebase prohibits it.

### Why this matters for retry logic

The beat task finds `PROCESSING` payouts and may reset them to `PENDING` for retry. Without the state machine, a bug could set a `COMPLETED` payout back to `PENDING`, causing a double payout. With the state machine, `completed → pending` raises `ValueError`.

---

## 5. The Celery Architecture

### process_payout (worker task)

Lifecycle:
1. **Lock + transition**: `PENDING → PROCESSING` in one transaction
2. **Simulate bank call**: outside transaction (takes real time; holding a DB transaction open for network I/O is a deadlock risk)
3. **Lock + finalize**: `PROCESSING → COMPLETED` or `PROCESSING → FAILED` in a second transaction

Outcomes are simulated: 70% success, 20% failure, 10% hung (no-op — beat task handles this).

### retry_stuck_payouts (beat task)

Runs every 15 seconds. Finds `PROCESSING` payouts whose deadline has passed:

| Attempt | Backoff |
|---------|---------|
| 1st | 30s |
| 2nd | 60s |
| 3rd | 120s |
| 4th+ | **FAILED** + funds returned |

The retry resets status to `PENDING` (bypassing `transition_to()` directly via `p.status = Payout.PENDING` — this is the one intentional exception, documented here). Then `process_payout.delay()` requeues it.

---

## 6. Why Celery Task Is Dispatched After the Transaction

```python
# CORRECT: outside transaction.atomic()
process_payout.delay(str(payout.id))
```

If `process_payout.delay()` were called inside `transaction.atomic()`, the Celery worker could pick up the task before the database transaction commits. The worker would query for the payout, find nothing (it's not committed yet), and silently exit.

Dispatching after the `with transaction.atomic():` block guarantees the payout row is visible to the worker before it starts.

---

## 7. Test Strategy

### `TransactionTestCase` vs `TestCase`

The concurrency test uses `TransactionTestCase`, not `TestCase`. Django's `TestCase` wraps the entire test in a transaction that is rolled back at the end — but this means `SELECT FOR UPDATE` inside a nested transaction may not block correctly across threads.

`TransactionTestCase` truncates tables after each test (slower) but allows real transaction boundaries, making database-level locking testable.

### What the concurrency test proves

Two threads, same merchant, 6,000 paise each, 10,000 paise balance:
- Exactly one 201 response (payout created)
- Exactly one 400 response (insufficient balance)
- Balance invariant: `10,000 - 6,000 = 4,000` paise

This is a **proof, not a check** — it fails reliably if you remove `select_for_update()`.
