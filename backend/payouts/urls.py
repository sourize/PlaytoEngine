from django.urls import path
from .views import PayoutCreateView, PayoutListView, PayoutDetailView

urlpatterns = [
    path('payouts/', PayoutCreateView.as_view()),
    path('payouts/list/', PayoutListView.as_view()),
    path('payouts/<uuid:pk>/', PayoutDetailView.as_view()),
]
