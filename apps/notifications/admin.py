from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "kind", "title", "read_at", "organization")
    list_filter = ("organization", "kind")
