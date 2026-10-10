from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("healthz/", views.healthz, name="healthz"),
    path("internal/jobs/<slug:name>/", views.run_job, name="run_job"),
]
