from django.urls import path
from .views import MerchantListView, MerchantDetailView

urlpatterns = [
    path('merchants/', MerchantListView.as_view()),
    path('merchants/<int:pk>/', MerchantDetailView.as_view()),
]
