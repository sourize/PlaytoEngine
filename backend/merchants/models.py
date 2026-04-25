from django.db import models
from django.db.models import Sum


class Merchant(models.Model):
    name = models.CharField(max_length=255)
    email = models.EmailField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def get_balance(self):
        """
        The TRUE balance — sum of ALL ledger entries for this merchant.
        Signed: credits are positive, debit holds are negative, releases are positive.
        This single query is the invariant we check.
        """
        result = self.ledger_entries.aggregate(total=Sum('amount_paise'))
        return result['total'] or 0

    def get_held_balance(self):
        """Funds tied up in in-flight payouts (for display only)."""
        from payouts.models import Payout
        result = self.payouts.filter(
            status__in=[Payout.PENDING, Payout.PROCESSING]
        ).aggregate(total=Sum('amount_paise'))
        return result['total'] or 0

    def __str__(self):
        return self.name


class LedgerEntry(models.Model):
    """
    Append-only ledger. We never update or delete rows here.
    Balance = SUM(amount_paise) for a merchant — always.

    Entry types:
      CREDIT       → positive amount  (customer paid merchant)
      DEBIT_HOLD   → negative amount  (payout requested, funds held)
      DEBIT_RELEASE → positive amount (payout failed, funds returned)

    Why not separate credits/debits tables? Because a single SUM() across
    all signed entries gives us the balance in one query with no possibility
    of the credit-sum and debit-sum getting out of sync.
    """
    CREDIT = 'credit'
    DEBIT_HOLD = 'debit_hold'
    DEBIT_RELEASE = 'debit_release'

    ENTRY_TYPES = [
        (CREDIT, 'Credit'),
        (DEBIT_HOLD, 'Debit Hold'),
        (DEBIT_RELEASE, 'Debit Release'),
    ]

    merchant = models.ForeignKey(
        Merchant,
        on_delete=models.PROTECT,
        related_name='ledger_entries'
    )
    # NEVER use FloatField or DecimalField for money.
    # BigIntegerField stores paise as an exact integer — no rounding errors ever.
    amount_paise = models.BigIntegerField()
    entry_type = models.CharField(max_length=20, choices=ENTRY_TYPES)
    payout = models.ForeignKey(
        'payouts.Payout',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='ledger_entries'
    )
    description = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.entry_type}: {self.amount_paise} paise for {self.merchant}"
