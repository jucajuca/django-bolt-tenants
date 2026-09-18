from django.contrib import admin

from tenants.models import Client, Domain


class DomainInline(admin.TabularInline):
    model = Domain
    extra = 0


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ("schema_name", "name", "created_on")
    search_fields = ("schema_name", "name")
    inlines = [DomainInline]


@admin.register(Domain)
class DomainAdmin(admin.ModelAdmin):
    list_display = ("domain", "tenant", "is_primary")
    list_filter = ("is_primary",)
    search_fields = ("domain", "tenant__schema_name")
