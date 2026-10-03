from django.contrib import admin

from .models import Organization, User


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "created_at")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("email", "role", "organization", "is_staff")
    list_filter = ("role", "organization")
    search_fields = ("email",)
    fields = (
        "email",
        "first_name",
        "last_name",
        "phone",
        "role",
        "organization",
        "is_active",
        "is_staff",
        "is_superuser",
    )
