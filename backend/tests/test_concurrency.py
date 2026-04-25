"""
Concurrency test: Two simultaneous 60-rupee requests against a 100-rupee balance.
Exactly one must succeed, one must fail. No overdraft.

Uses TransactionTestCase (not TestCase) because we need real transactions to
test database-level locking — TestCase wraps everything in a single transaction
which would make SELECT FOR UPDATE behave differently.
"""
import json
import threading
from django.test import TransactionTestCase, Client
from merchants.models import Merchant, LedgerEntry
from payouts.models import Payout


class ConcurrencyTest(TransactionTestCase):

    def setUp(self):
        self.merchant = Merchant.objects.create(
            name='Concurrent Test Merchant',
            email='concurrent@test.com',
        )
        # Seed 100 rupees (10,000 paise)
        LedgerEntry.objects.create(
            merchant=self.merchant,
            amount_paise=10_000,
            entry_type=LedgerEntry.CREDIT,
            description='Initial balance',
        )

    def test_two_concurrent_payouts_only_one_succeeds(self):
        """
        Two threads simultaneously request 6,000 paise each (100 rupee balance).
        Exactly one should succeed (201), the other should fail (400).
        """
        results = []
        errors = []

        def request_payout(idempotency_key):
            client = Client()
            try:
                response = client.post(
                    '/api/v1/payouts/',
                    data=json.dumps({
                        'merchant_id': self.merchant.id,
                        'amount_paise': 6_000,
                        'bank_account_id': 'HDFC001',
                    }),
                    content_type='application/json',
                    **{'HTTP_IDEMPOTENCY_KEY': idempotency_key},
                )
                results.append(response.status_code)
            except Exception as e:
                errors.append(str(e))

        t1 = threading.Thread(target=request_payout, args=('key-concurrent-1',))
        t2 = threading.Thread(target=request_payout, args=('key-concurrent-2',))

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertEqual(errors, [], f"Unexpected errors: {errors}")
        self.assertIn(201, results, "One request should have succeeded (201)")
        self.assertIn(400, results, "One request should have failed (400)")
        self.assertEqual(results.count(201), 1, "Exactly one should succeed")
        self.assertEqual(results.count(400), 1, "Exactly one should be rejected")

        # Verify: only one payout created
        self.assertEqual(
            Payout.objects.filter(merchant=self.merchant).count(), 1
        )

        # Verify: balance invariant holds (10,000 - 6,000 = 4,000)
        self.assertEqual(self.merchant.get_balance(), 4_000)
