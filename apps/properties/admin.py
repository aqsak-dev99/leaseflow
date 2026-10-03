from django.contrib import admin

from .models import Lease, Property, Unit


@admin.register(Property)
class PropertyAdmin(admin.ModelAdmin):
    list_display = ("name", "city", "organization")
    list_filter = ("organization",)


@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ("unit_number", "property", "monthly_rent", "status", "organization")
    list_filter = ("organization", "status")


@admin.register(Lease)
class LeaseAdmin(admin.ModelAdmin):
    list_display = ("unit", "tenant", "start_date", "end_date", "status", "organization")
    list_filter = ("organization", "status")
