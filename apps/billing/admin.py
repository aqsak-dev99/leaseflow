from django.contrib import admin

from .models import Invoice, Payment, WebhookEvent


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ("id", "lease", "period", "amount", "due_date", "status", "organization")
    list_filter = ("organization", "status")


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("id", "invoice", "amount", "provider", "status", "paid_at")
    list_filter = ("organization", "provider", "status")


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = ("id", "provider", "event_id", "received_at", "processed_at", "payment")
