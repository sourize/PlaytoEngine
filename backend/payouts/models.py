import uuid
from django.db import models
from django.utils import timezone


class Payout(models.Model):
    PENDING = 'pending'
    PROCESSING = 'processing'
    COMPLETED = 'completed'
    FAILED = 'failed'

    STATUS_CHOICES = [
        (PENDING, 'Pending'),
        (PROCESSING, 'Processing'),
        (COMPLETED, 'Completed'),
        (FAILED, 'Failed'),
    ]

    # Explicit legal transitions — everything else is illegal
    VALID_TRANSITIONS = {
        PENDING: [PROCESSING],
        PROCESSING: [COMPLETED, FAILED],
        COMPLETED: [],   # Terminal — no way out
        FAILED: [],      # Terminal — no way out
    }

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    merchant = models.ForeignKey(
        'merchants.Merchant',
        on_delete=models.PROTECT,
        related_name='payouts'
    )
    amount_paise = models.BigIntegerField()
    bank_account_id = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PENDING)

    # Idempotency: scoped per merchant, unique together enforced at DB level
    idempotency_key = models.CharField(max_length=255)

    attempt_count = models.IntegerField(default=0)
    processing_started_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # DB-level uniqueness: same merchant cannot have two payouts with the same key
        unique_together = [['merchant', 'idempotency_key']]
        ordering = ['-created_at']

    def transition_to(self, new_status):
        """
        The state machine gate. Call this instead of setting .status directly.
        This is where failed→completed and completed→pending are BLOCKED.
        """
        allowed = self.VALID_TRANSITIONS.get(self.status, [])
        if new_status not in allowed:
            raise ValueError(
                f"Illegal state transition: {self.status} → {new_status}. "
                f"Allowed from {self.status}: {allowed}"
            )
        self.status = new_status

    def __str__(self):
        return f"Payout {self.id} ({self.status}) — {self.amount_paise} paise"
