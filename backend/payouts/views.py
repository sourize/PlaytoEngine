from django.db import transaction, IntegrityError
from django.db.models import Sum
from django.utils import timezone
from datetime import timedelta
from rest_framework.views import APIView
from rest_framework.response import Response

from merchants.models import Merchant, LedgerEntry
from .models import Payout
from .serializers import PayoutSerializer
from .tasks import process_payout


IDEMPOTENCY_KEY_TTL_HOURS = 24


class PayoutCreateView(APIView):
    def post(self, request):
        # --- Validate headers ---
        idempotency_key = request.headers.get('Idempotency-Key', '').strip()
        if not idempotency_key:
            return Response({'error': 'Idempotency-Key header is required'}, status=400)

        # --- Validate body ---
        merchant_id = request.data.get('merchant_id')
        amount_paise = request.data.get('amount_paise')
        bank_account_id = request.data.get('bank_account_id')

        if not all([merchant_id, amount_paise, bank_account_id]):
            return Response({'error': 'merchant_id, amount_paise, bank_account_id required'}, status=400)

        try:
            amount_paise = int(amount_paise)
        except (TypeError, ValueError):
            return Response({'error': 'amount_paise must be an integer'}, status=400)

        if amount_paise <= 0:
            return Response({'error': 'amount_paise must be positive'}, status=400)

        key_expiry = timezone.now() - timedelta(hours=IDEMPOTENCY_KEY_TTL_HOURS)

        # --- Fast-path idempotency check (no lock needed, read-only) ---
        # If we've seen this key before and it hasn't expired, return immediately
        existing = Payout.objects.filter(
            merchant_id=merchant_id,
            idempotency_key=idempotency_key,
            created_at__gte=key_expiry,
        ).first()
        if existing:
            return Response(PayoutSerializer(existing).data, status=200)

        # --- Main transactional path ---
        try:
            with transaction.atomic():
                # SELECT FOR UPDATE: This is the concurrency primitive.
                # It acquires a row-level exclusive lock on the merchant row.
                # Any other transaction trying to SELECT FOR UPDATE the same
                # merchant will BLOCK here until we commit or rollback.
                # This turns "check-then-deduct" from a race condition into
                # a serialized operation — exactly what we need.
                try:
                    merchant = Merchant.objects.select_for_update().get(id=merchant_id)
                except Merchant.DoesNotExist:
                    return Response({'error': 'Merchant not found'}, status=404)

                # --- Second idempotency check (inside lock) ---
                # Handles the race: two requests with the SAME key arrive
                # simultaneously. Both pass the fast-path check above (key not
                # found yet). The first acquires the lock and creates the payout.
                # The second acquires the lock and finds the payout here.
                existing = Payout.objects.filter(
                    merchant=merchant,
                    idempotency_key=idempotency_key,
                    created_at__gte=key_expiry,
                ).first()
                if existing:
                    return Response(PayoutSerializer(existing).data, status=200)

                # --- Balance check at DB level ---
                # We do NOT fetch the balance into Python and subtract there.
                # We compute the sum in the database. This is the only correct
                # way — Python arithmetic on fetched rows is a TOCTOU bug.
                balance = LedgerEntry.objects.filter(
                    merchant=merchant
                ).aggregate(total=Sum('amount_paise'))['total'] or 0

                if balance < amount_paise:
                    return Response(
                        {'error': f'Insufficient balance. Have {balance} paise, need {amount_paise} paise'},
                        status=400
                    )

                # --- Create payout and hold funds atomically ---
                payout = Payout.objects.create(
                    merchant=merchant,
                    amount_paise=amount_paise,
                    bank_account_id=bank_account_id,
                    idempotency_key=idempotency_key,
                    status=Payout.PENDING,
                )

                # The debit hold: immediately reduces available balance.
                # If the payout fails later, we add a DEBIT_RELEASE entry
                # (positive amount) to restore the balance.
                LedgerEntry.objects.create(
                    merchant=merchant,
                    amount_paise=-amount_paise,  # negative = reduces balance
                    entry_type=LedgerEntry.DEBIT_HOLD,
                    payout=payout,
                    description=f'Hold for payout {payout.id}',
                )

        except IntegrityError:
            # Last resort: DB unique constraint on (merchant, idempotency_key)
            # caught a race we didn't handle above. Return the existing payout.
            existing = Payout.objects.filter(
                merchant_id=merchant_id,
                idempotency_key=idempotency_key,
            ).first()
            if existing:
                return Response(PayoutSerializer(existing).data, status=200)
            return Response({'error': 'Conflict'}, status=409)

        # Dispatch background task — AFTER the transaction commits
        # (if we called it inside the transaction, the worker might pick it up
        # before the DB commit, find no payout, and exit silently)
        process_payout.delay(str(payout.id))

        return Response(PayoutSerializer(payout).data, status=201)


class PayoutListView(APIView):
    def get(self, request):
        merchant_id = request.query_params.get('merchant_id')
        qs = Payout.objects.all()
        if merchant_id:
            qs = qs.filter(merchant_id=merchant_id)
        return Response(PayoutSerializer(qs[:50], many=True).data)


class PayoutDetailView(APIView):
    def get(self, request, pk):
        try:
            payout = Payout.objects.get(pk=pk)
        except Payout.DoesNotExist:
            return Response({'error': 'Not found'}, status=404)
        return Response(PayoutSerializer(payout).data)
