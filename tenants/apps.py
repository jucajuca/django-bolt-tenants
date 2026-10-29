from django.apps import AppConfig


class TenantsConfig(AppConfig):
    name = 'tenants'

    def ready(self):
        # Site <-> Domain mirror (Site.pk == Organization.id)
        from tenants import signals  # noqa: F401
