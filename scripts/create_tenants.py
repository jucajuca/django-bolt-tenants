"""Seed tenants for the django-bolt + django-tenants experiment.

Usage:
    python manage.py shell < scripts/create_tenants.py

Creates the required `public` tenant plus a couple of demo tenants with
matching domain records. Idempotent: existing tenants/domains are left alone.
"""

from tenants.models import Client, Domain

TENANTS = {
    "public": "localhost",
    "acme": "acme.localhost",
    "beta": "beta.localhost",
}

for schema_name, domain in TENANTS.items():
    tenant, created = Client.objects.get_or_create(
        schema_name=schema_name, defaults={"name": schema_name.title()}
    )
    Domain.objects.get_or_create(
        domain=domain, defaults={"tenant": tenant, "is_primary": True}
    )
    print(f"{'created' if created else 'exists'}: {schema_name} -> {domain}")
