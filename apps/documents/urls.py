from django.urls import path

from . import views

app_name = "documents"

urlpatterns = [
    path(
        "documents/<int:document_id>/page/<int:page_number>/",
        views.document_page,
        name="page",
    ),
    path("documents/<int:document_id>/file/", views.document_file, name="file"),
]
