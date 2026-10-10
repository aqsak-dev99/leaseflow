from django.urls import path

from . import views

app_name = "properties"

urlpatterns = [
    path("properties/add/", views.property_add, name="property_add"),
    path("properties/<int:property_id>/units/add/", views.unit_add, name="unit_add"),
    path("units/<int:unit_id>/invite/", views.unit_invite, name="invite"),
    path(
        "invitations/<int:invitation_id>/cancel/", views.invitation_cancel, name="cancel"
    ),
    path(
        "invitations/<int:invitation_id>/resend/", views.invitation_resend, name="resend"
    ),
    path("invite/<str:token>/", views.invitation_accept, name="accept"),
]
