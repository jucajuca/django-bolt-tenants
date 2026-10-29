"""Seed tenants for the django-bolt + django-tenants experiment.

Usage:
    python manage.py shell < scripts/create_tenants.py

Creates the required `public` tenant (serving MAIN_DOMAIN) plus a couple of
demo tenants with matching subdomain records. The Site <-> Domain signal mirror
(tenants/signals.py) creates one Site per tenant with Site.pk == tenant id.
Idempotent: existing tenants/domains are left alone.
"""

from django.conf import settings

from tenants.models import Domain, Organization

main_domain = settings.MAIN_DOMAIN

TENANTS = {
    "public": main_domain,
    "acme": f"acme.{main_domain}",
    "beta": f"beta.{main_domain}",
}

for schema_name, domain in TENANTS.items():
    tenant, created = Organization.objects.get_or_create(
        schema_name=schema_name, defaults={"name": schema_name.title()}
    )
    Domain.objects.get_or_create(
        domain=domain, defaults={"tenant": tenant, "is_primary": True}
    )
    print(f"{'created' if created else 'exists'}: {schema_name} -> {domain}")
