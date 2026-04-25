import random
import logging
from celery import shared_task
from django.db import transaction
from django.utils import timezone
from datetime import timedelta

from merchants.models import LedgerEntry

logger = logging.getLogger(__name__)


@shared_task(bind=True)
def process_payout(self, payout_id: str):
    """
    Moves a payout through its lifecycle.
    Simulate: 70% success, 20% failure, 10% hung (no outcome).
    """
    from .models import Payout

    # Step 1: Transition PENDING → PROCESSING
    with transaction.atomic():
        try:
            payout = Payout.objects.select_for_update().get(id=payout_id)
        except Payout.DoesNotExist:
            logger.warning(f"Payout {payout_id} not found")
            return

        if payout.status != Payout.PENDING:
            logger.info(f"Payout {payout_id} is {payout.status}, skipping")
            return

        try:
            payout.transition_to(Payout.PROCESSING)
        except ValueError as e:
            logger.error(f"State machine error: {e}")
            return

        payout.processing_started_at = timezone.now()
        payout.attempt_count += 1
        payout.save()

    # Step 2: Simulate bank call (outside transaction — this takes time)
    outcome = random.choices(
        ['success', 'failure', 'hung'],
        weights=[70, 20, 10]
    )[0]

    logger.info(f"Payout {payout_id} -> outcome: {outcome}")

    if outcome == 'hung':
        # Do nothing. retry_stuck_payouts beat task will catch this
        # after 30s (with exponential backoff) and requeue or fail it.
        return

    # Step 3: Finalize with atomic state transition
    with transaction.atomic():
        try:
            payout = Payout.objects.select_for_update().get(id=payout_id)
        except Payout.DoesNotExist:
            return

        if payout.status != Payout.PROCESSING:
            # Something else already handled this payout (e.g., retry logic)
            return

        if outcome == 'success':
            payout.transition_to(Payout.COMPLETED)
            payout.save()
            logger.info(f"Payout {payout_id} completed successfully")

        elif outcome == 'failure':
            payout.transition_to(Payout.FAILED)
            payout.save()

            # Return funds ATOMICALLY in the same transaction as status change.
            # If this write fails, the status update also rolls back.
            # The merchant will never be in a state where status=FAILED but funds not returned.
            LedgerEntry.objects.create(
                merchant=payout.merchant,
                amount_paise=payout.amount_paise,  # positive = restores balance
                entry_type=LedgerEntry.DEBIT_RELEASE,
                payout=payout,
                description=f'Refund for failed payout {payout.id}',
            )
            logger.info(f"Payout {payout_id} failed — {payout.amount_paise} paise returned")


@shared_task
def retry_stuck_payouts():
    """
    Celery beat task — runs every 15 seconds.
    Finds payouts stuck in PROCESSING and either retries or fails them.
    Exponential backoff: wait 30s * 2^(attempt_count-1) before retrying.
    Max 3 attempts, then FAILED.
    """
    from .models import Payout

    now = timezone.now()
    # Find all PROCESSING payouts where enough time has passed for their attempt
    processing_payouts = Payout.objects.filter(
        status=Payout.PROCESSING,
        processing_started_at__isnull=False,
    )

    for payout in processing_payouts:
        # Exponential backoff: 30s, 60s, 120s
        backoff_seconds = 30 * (2 ** (payout.attempt_count - 1))
        deadline = payout.processing_started_at + timedelta(seconds=backoff_seconds)

        if now < deadline:
            continue  # Not stuck yet for this attempt

        with transaction.atomic():
            # Re-fetch with lock to avoid races with process_payout
            try:
                p = Payout.objects.select_for_update().get(id=payout.id)
            except Payout.DoesNotExist:
                continue

            if p.status != Payout.PROCESSING:
                continue  # Already handled

            if p.attempt_count >= 3:
                # Out of retries — fail and return funds
                p.transition_to(Payout.FAILED)
                p.save()

                LedgerEntry.objects.create(
                    merchant=p.merchant,
                    amount_paise=p.amount_paise,
                    entry_type=LedgerEntry.DEBIT_RELEASE,
                    payout=p,
                    description=f'Refund for stuck payout {p.id} (max retries exceeded)',
                )
                logger.info(f"Payout {p.id} permanently failed after {p.attempt_count} attempts")
            else:
                # Reset to PENDING so process_payout can pick it up again
                p.status = Payout.PENDING
                p.processing_started_at = None
                p.save()

                process_payout.delay(str(p.id))
                logger.info(f"Retrying stuck payout {p.id} (attempt {p.attempt_count})")
