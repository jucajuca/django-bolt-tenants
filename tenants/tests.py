"""Site <-> Domain mirror invariant tests.

The signal mirror (tenants/signals.py) keeps exactly one Site per Organization,
keyed by Site.pk == Organization.id. These tests pin that invariant without
creating real schemas (auto_create_schema is disabled per-instance so no DDL
runs inside the test transaction).
"""

from django.contrib.sites.models import Site
from django.db import connection
from django.test import TestCase

from tenants.models import Domain, Organization


def make_organization(schema_name: str, domain: str) -> Organization:
    # Other tests may leave the connection scoped to a tenant schema.
    connection.set_schema_to_public()
    tenant = Organization(schema_name=schema_name, name=schema_name.title())
    # Skip schema creation: DDL cannot be rolled back inside a test transaction.
    tenant.auto_create_schema = False
    tenant.save()
    Domain.objects.create(domain=domain, tenant=tenant, is_primary=True)
    return tenant


class SiteSyncTests(TestCase):
    def test_site_created_with_tenant_pk(self):
        org = make_organization("site_acme", "site-acme.myapp.com")
        site = Site.objects.get(pk=org.pk)
        self.assertEqual(site.domain, "site-acme.myapp.com")
        self.assertEqual(site.name, "site-acme.myapp.com")

    def test_rename_updates_site_in_place(self):
        org = make_organization("site_acme", "site-acme.myapp.com")
        domain = org.domains.get()
        domain.domain = "site-acme2.myapp.com"
        domain.save()

        # Exactly one Site remains, updated to the new hostname.
        self.assertEqual(Site.objects.filter(pk=org.pk).count(), 1)
        self.assertEqual(Site.objects.get(pk=org.pk).domain, "site-acme2.myapp.com")
        # The old hostname is gone (no duplicate left behind).
        self.assertEqual(Site.objects.filter(domain="site-acme.myapp.com").count(), 0)

    def test_delete_domain_removes_site(self):
        org = make_organization("site_acme", "site-acme.myapp.com")
        org.domains.get().delete()
        self.assertFalse(Site.objects.filter(pk=org.pk).exists())

    def test_secondary_domain_does_not_create_site(self):
        org = make_organization("site_acme", "site-acme.myapp.com")
        Domain.objects.create(
            domain="acme-alias.myapp.com", tenant=org, is_primary=False
        )
        # Still exactly one Site for the tenant, still the primary hostname.
        self.assertEqual(Site.objects.filter(pk=org.pk).count(), 1)
        self.assertEqual(Site.objects.get(pk=org.pk).domain, "site-acme.myapp.com")

    def test_main_domain_site_not_duplicated(self):
        """A tenant serving MAIN_DOMAIN gets its Site without duplicating the
        hostname across Site rows."""
        make_organization("site_public", "myapp.com")
        self.assertEqual(Site.objects.filter(domain="myapp.com").count(), 1)
