from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.home, name="home"),
    path("htmx-check/", views.htmx_check, name="htmx_check"),
]
