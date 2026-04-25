from rest_framework import serializers
from .models import Payout


class PayoutSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payout
        fields = [
            'id', 'merchant_id', 'amount_paise', 'bank_account_id',
            'status', 'idempotency_key', 'attempt_count',
            'created_at', 'updated_at'
        ]
