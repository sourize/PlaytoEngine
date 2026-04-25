"""
Idempotency test: Same key sent twice returns the same response, no duplicate payout.
"""
import json
from django.test import TestCase, Client
from merchants.models import Merchant, LedgerEntry
from payouts.models import Payout


class IdempotencyTest(TestCase):

    def setUp(self):
        self.merchant = Merchant.objects.create(
            name='Idempotency Test Merchant',
            email='idempotency@test.com',
        )
        LedgerEntry.objects.create(
            merchant=self.merchant,
            amount_paise=50_000,
            entry_type=LedgerEntry.CREDIT,
            description='Test balance',
        )
        self.client = Client()

    def _post_payout(self, key):
        return self.client.post(
            '/api/v1/payouts/',
            data=json.dumps({
                'merchant_id': self.merchant.id,
                'amount_paise': 1_000,
                'bank_account_id': 'ICICI001',
            }),
            content_type='application/json',
            **{'HTTP_IDEMPOTENCY_KEY': key},
        )

    def test_same_key_returns_same_payout(self):
        """Second request with same key returns 200 with identical payout."""
        r1 = self._post_payout('idem-key-abc-123')
        r2 = self._post_payout('idem-key-abc-123')

        self.assertEqual(r1.status_code, 201, "First request must succeed")
        self.assertEqual(r2.status_code, 200, "Second request must return cached response")
        self.assertEqual(r1.json()['id'], r2.json()['id'], "Must return same payout ID")

        # Only one payout and one ledger entry created
        self.assertEqual(Payout.objects.filter(merchant=self.merchant).count(), 1)
        self.assertEqual(
            LedgerEntry.objects.filter(merchant=self.merchant, entry_type=LedgerEntry.DEBIT_HOLD).count(),
            1
        )

    def test_different_keys_create_different_payouts(self):
        """Different keys create separate payouts independently."""
        r1 = self._post_payout('key-one')
        r2 = self._post_payout('key-two')

        self.assertEqual(r1.status_code, 201)
        self.assertEqual(r2.status_code, 201)
        self.assertNotEqual(r1.json()['id'], r2.json()['id'])
        self.assertEqual(Payout.objects.filter(merchant=self.merchant).count(), 2)

    def test_expired_key_allows_new_payout(self):
        """A key older than 24 hours is treated as new."""
        from django.utils import timezone
        from datetime import timedelta

        # Create an old payout with this key
        old_payout = Payout.objects.create(
            merchant=self.merchant,
            amount_paise=1_000,
            bank_account_id='OLD',
            idempotency_key='expired-key',
            status=Payout.COMPLETED,
        )
        # Backdate it beyond the 24h TTL
        Payout.objects.filter(id=old_payout.id).update(
            created_at=timezone.now() - timedelta(hours=25)
        )

        # A new request with the same key should create a NEW payout
        r = self._post_payout('expired-key')
        self.assertEqual(r.status_code, 201)
        self.assertNotEqual(r.json()['id'], str(old_payout.id))
