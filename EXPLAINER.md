# Playto Payout — EXPLAINER.md

> Answers to the five specific questions from the brief. Short, specific, honest.

---

## 1. The Ledger

**Balance calculation query:**

```python
# merchants/models.py — Merchant.get_balance()
result = self.ledger_entries.aggregate(total=Sum('amount_paise'))
return result['total'] or 0
```

Which issues:
```sql
SELECT SUM(amount_paise) FROM merchants_ledgerentry WHERE merchant_id = ?
```

**Why I modelled credits and debits this way:**

Balance is never a stored column — it is always derived. Every money movement appends a signed row to `LedgerEntry`:

| Entry type | Sign | When |
|------------|------|------|
| `credit` | **+** | Customer payment received (seeded) |
| `debit_hold` | **−** | Payout requested, funds reserved |
| `debit_release` | **+** | Payout failed, funds returned |

A single `SUM()` over all signed entries is always the true balance. There is no credit-column and debit-column that can drift apart — there is only one column, and the sign encodes direction.

Amounts are stored as `BigIntegerField` in paise. `FloatField` accumulates rounding error across millions of operations. `150 paise = ₹1.50` — integer arithmetic, exact every time.

---

## 2. The Lock

**Exact code that prevents two concurrent payouts from overdrawing:**

```python
# payouts/views.py — PayoutCreateView.post()
with transaction.atomic():
    merchant = Merchant.objects.select_for_update().get(id=merchant_id)

    balance = LedgerEntry.objects.filter(
        merchant=merchant
    ).aggregate(total=Sum('amount_paise'))['total'] or 0

    if balance < amount_paise:
        return Response({'error': 'Insufficient balance'}, status=400)

    payout = Payout.objects.create(...)
    LedgerEntry.objects.create(amount_paise=-amount_paise, ...)
```

**The database primitive:** `SELECT ... FOR UPDATE` — a row-level exclusive lock on the merchant row in PostgreSQL.

When Request A calls `select_for_update()`, PostgreSQL locks that merchant row. When Request B arrives with the same merchant, it **blocks at the database level** — not in Python, not in Django — until Request A's transaction commits or rolls back.

This serializes all payouts for a given merchant:

```
Request A: acquires lock → checks balance (1000) → deducts 600 → commits → releases lock
Request B: blocks ─────────────────────────────────────────────────→ sees balance (400) → rejects
```

The `SUM()` and the `INSERT` both happen inside the same `transaction.atomic()` block with the lock held. They are atomic together.

---

## 3. The Idempotency

**How the system knows it has seen a key before:**

Every `Payout` stores the client-supplied `Idempotency-Key` header value. A database unique constraint enforces no duplicates:

```python
# payouts/models.py
class Meta:
    unique_together = [['merchant', 'idempotency_key']]
```

On every `POST /api/v1/payouts/`, the view queries for an existing payout with that `(merchant, key)` pair within the 24-hour TTL before doing any work.

**What happens if the first request is in-flight when the second arrives (the hard case):**

I use a double-check pattern:

**Check 1 — fast path, no lock:**
```python
existing = Payout.objects.filter(
    merchant_id=merchant_id,
    idempotency_key=idempotency_key,
    created_at__gte=key_expiry,
).first()
if existing:
    return Response(PayoutSerializer(existing).data, status=200)
```

If the first request has already committed, the second returns immediately here.

**Check 2 — inside the lock:**
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

If two requests with the **same key** arrive simultaneously, both pass Check 1 (key doesn't exist yet). The first acquires the lock and creates the payout. The second acquires the lock after the first commits — Check 2 finds the payout and returns it.

**Last resort:** If both somehow slip through (theoretically impossible but defensively handled), the DB unique constraint raises `IntegrityError`, caught by the view and returned as a 200 with the existing payout.

Keys are scoped per merchant (`unique_together`) and expire after 24 hours.

---

## 4. The State Machine

**Where `failed → completed` (and all illegal transitions) are blocked:**

```python
# payouts/models.py — Payout.transition_to()

VALID_TRANSITIONS = {
    PENDING:    [PROCESSING],
    PROCESSING: [COMPLETED, FAILED],
    COMPLETED:  [],   # Terminal — no outgoing edges
    FAILED:     [],   # Terminal — no outgoing edges
}

def transition_to(self, new_status):
    allowed = self.VALID_TRANSITIONS.get(self.status, [])
    if new_status not in allowed:
        raise ValueError(
            f"Illegal transition: {self.status} → {new_status}. "
            f"Allowed from {self.status}: {allowed}"
        )
    self.status = new_status
```

`COMPLETED: []` and `FAILED: []` mean no transition out of either state is ever allowed. Any attempt raises `ValueError`.

`transition_to()` is the only way to change status in the codebase. The one exception is the retry task resetting a hung payout to `PENDING` — which is intentional and documented as such in `tasks.py`.

**Fund return is atomic with the state transition:** When a payout fails, the `DEBIT_RELEASE` ledger entry is written in the same `transaction.atomic()` block as `transition_to(FAILED)`. If either write fails, both roll back. A merchant can never be in a state where `status=FAILED` but funds are not returned.

```python
# payouts/tasks.py
with transaction.atomic():
    payout.transition_to(Payout.FAILED)
    payout.save()
    LedgerEntry.objects.create(
        amount_paise=payout.amount_paise,   # positive — restores balance
        entry_type=LedgerEntry.DEBIT_RELEASE,
        ...
    )
```

---

## 5. The AI Audit

**What AI gave me, what I caught, and what I replaced it with:**

When I asked an AI to write the balance check inside the payout creation view, it generated:

```python
# WHAT AI WROTE — subtly wrong
merchant.refresh_from_db()
if merchant.balance < amount_paise:
    return Response({'error': 'Insufficient balance'}, status=400)
LedgerEntry.objects.create(amount_paise=-amount_paise, ...)
```

This code assumes `merchant.balance` is a stored column (it isn't — balance is derived). Even if it were, this is a classic TOCTOU bug: `refresh_from_db()` reads the value into Python memory. Between that read and the `LedgerEntry INSERT`, another transaction can write a competing debit. The check and the write are not atomic — they are two separate database round-trips.

**What I replaced it with:**

```python
# WHAT I WROTE — correct
with transaction.atomic():
    merchant = Merchant.objects.select_for_update().get(id=merchant_id)

    balance = LedgerEntry.objects.filter(
        merchant=merchant
    ).aggregate(total=Sum('amount_paise'))['total'] or 0

    if balance < amount_paise:
        return Response({'error': 'Insufficient balance'}, status=400)

    LedgerEntry.objects.create(amount_paise=-amount_paise, ...)
```

Three differences:
1. `select_for_update()` acquires the row lock — no other transaction can debit this merchant while we hold it
2. `aggregate(Sum(...))` computes balance at the **database level inside the transaction** — not a Python variable read from a fetched row
3. The check and the write are in the same `transaction.atomic()` block — they are atomic together

The AI's version would pass unit tests but fail under concurrent load. The concurrency test (`test_concurrency.py`) fails reliably with the AI version and passes with the corrected version.

---

## Architecture Notes

### Why Celery task is dispatched after `transaction.atomic()`

```python
# OUTSIDE the with block — correct
process_payout.delay(str(payout.id))
```

If `.delay()` were called inside the transaction, the Celery worker could pick up the task before the commit — query for the payout, find nothing, and exit silently. Dispatching after commit guarantees the row is visible.

### Why `TransactionTestCase` for the concurrency test

Django's `TestCase` wraps each test in a transaction that rolls back at the end. But this means `SELECT FOR UPDATE` inside that outer transaction does not block correctly across threads — the locks behave differently under a shared transaction boundary. `TransactionTestCase` uses real commits and truncates tables after each test, making database-level locking testable as it behaves in production.
