from django.contrib import admin

from .models import MaintenanceTicket, TicketUpdate


class TicketUpdateInline(admin.TabularInline):
    model = TicketUpdate
    extra = 0


@admin.register(MaintenanceTicket)
class MaintenanceTicketAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "unit", "category", "priority", "status", "organization")
    list_filter = ("organization", "status", "category", "priority")
    inlines = [TicketUpdateInline]
