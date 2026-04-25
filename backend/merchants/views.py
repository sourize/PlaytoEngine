from rest_framework.views import APIView
from rest_framework.response import Response
from .models import Merchant
from .serializers import MerchantSerializer


class MerchantListView(APIView):
    def get(self, request):
        merchants = Merchant.objects.all()
        return Response(MerchantSerializer(merchants, many=True).data)


class MerchantDetailView(APIView):
    def get(self, request, pk):
        try:
            merchant = Merchant.objects.get(pk=pk)
        except Merchant.DoesNotExist:
            return Response({'error': 'Not found'}, status=404)
        return Response(MerchantSerializer(merchant).data)
