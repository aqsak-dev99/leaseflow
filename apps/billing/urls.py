from django.urls import path

from . import views

app_name = "billing"

urlpatterns = [
    path("fake-gateway/<str:reference>/", views.fake_checkout, name="fake_checkout"),
    path("webhooks/fake-gateway/", views.fake_gateway_webhook, name="fake_gateway_webhook"),
]
