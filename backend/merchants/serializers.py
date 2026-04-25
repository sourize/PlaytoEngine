from rest_framework import serializers
from .models import Merchant, LedgerEntry


class LedgerEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = LedgerEntry
        fields = ['id', 'amount_paise', 'entry_type', 'description', 'created_at', 'payout_id']


class MerchantSerializer(serializers.ModelSerializer):
    available_balance = serializers.SerializerMethodField()
    held_balance = serializers.SerializerMethodField()
    recent_entries = serializers.SerializerMethodField()

    class Meta:
        model = Merchant
        fields = ['id', 'name', 'email', 'available_balance', 'held_balance', 'recent_entries']

    def get_available_balance(self, obj):
        return obj.get_balance()

    def get_held_balance(self, obj):
        return obj.get_held_balance()

    def get_recent_entries(self, obj):
        entries = obj.ledger_entries.all()[:20]
        return LedgerEntrySerializer(entries, many=True).data
