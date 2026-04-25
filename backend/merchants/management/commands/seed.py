from django.core.management.base import BaseCommand
from merchants.models import Merchant, LedgerEntry


class Command(BaseCommand):
    help = 'Seed database with test merchants and credit history'

    def handle(self, *args, **options):
        data = [
            {
                'name': 'Rahul Freelance',
                'email': 'rahul@example.com',
                'credits': [
                    (500_000, 'USD invoice #1001 — $625'),
                    (300_000, 'USD invoice #1002 — $375'),
                ],
            },
            {
                'name': 'Priya Design Studio',
                'email': 'priya@example.com',
                'credits': [
                    (1_000_000, 'USD invoice #2001 — $1,250'),
                    (250_000,   'USD invoice #2002 — $312.50'),
                    (750_000,   'USD invoice #2003 — $937.50'),
                ],
            },
            {
                'name': 'Dev Solutions',
                'email': 'dev@example.com',
                'credits': [
                    (200_000, 'USD invoice #3001 — $250'),
                    (800_000, 'USD invoice #3002 — $1,000'),
                ],
            },
        ]

        for item in data:
            merchant, created = Merchant.objects.get_or_create(
                email=item['email'],
                defaults={'name': item['name']},
            )
            if created:
                for amount, desc in item['credits']:
                    LedgerEntry.objects.create(
                        merchant=merchant,
                        amount_paise=amount,
                        entry_type=LedgerEntry.CREDIT,
                        description=desc,
                    )
                self.stdout.write(
                    self.style.SUCCESS(f"Created {merchant.name} with {len(item['credits'])} credits")
                )
            else:
                self.stdout.write(f"Skipped {merchant.name} (already exists)")
