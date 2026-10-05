from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.home, name="home"),
    path("properties/", views.properties, name="properties"),
    path("tickets/", views.tickets, name="tickets"),
    path("tickets/<int:ticket_id>/", views.ticket_detail, name="ticket_detail"),
    path("invoices/", views.invoices, name="invoices"),
    path("invoices/generate/", views.invoices_generate, name="invoices_generate"),
    path("invoices/<int:invoice_id>/pay/", views.invoice_pay, name="invoice_pay"),
    path(
        "invoices/<int:invoice_id>/record-payment/",
        views.invoice_record_payment,
        name="invoice_record_payment",
    ),
    path("approvals/", views.approvals, name="approvals"),
    path("approvals/check-overdue/", views.overdue_check_now, name="overdue_check_now"),
    path(
        "approvals/<int:request_id>/decide/", views.approval_decide, name="approval_decide"
    ),
    path("activity/", views.activity, name="activity"),
    path("runs/<int:run_id>/", views.run_detail, name="run_detail"),
    path("chat/", views.chat, name="chat"),
    path("chat/send/", views.chat_send, name="chat_send"),
    path("chat/new/", views.chat_new, name="chat_new"),
]
