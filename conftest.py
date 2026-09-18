import pytest
from django.db import connection

from django_bolt.testing import TestClient

from missions.api import api

# Domain -> tenant schema mapping used throughout the test suite.
# These are created once per test run (schema DDL cannot be rolled back inside
# a transaction), and the Bolt TestClient sends the matching Host header so
# django-tenants' TenantMainMiddleware switches to the right schema.
TENANTS = {
    "acme": "acme.localhost",
    "beta": "beta.localhost",
}


@pytest.fixture(scope="session")
def tenants_created(django_db_setup, django_db_blocker):
    """Create tenant schemas in the test database once for the whole session."""
    from tenants.models import Client, Domain

    with django_db_blocker.unblock():
        for schema_name, domain in TENANTS.items():
            if Client.objects.filter(schema_name=schema_name).exists():
                continue
            tenant = Client(schema_name=schema_name, name=schema_name.title())
            tenant.save()
            Domain.objects.create(domain=domain, tenant=tenant, is_primary=True)
        connection.set_schema_to_public()
    return TENANTS


@pytest.fixture
def client(tenants_created):
    """Bolt test client bound to the acme tenant host."""
    with TestClient(api, base_url=f"http://{TENANTS['acme']}") as client:
        yield client


@pytest.fixture
def beta_client(tenants_created):
    """Bolt test client bound to the beta tenant host."""
    with TestClient(api, base_url=f"http://{TENANTS['beta']}") as client:
        yield client
