import uuid

import pytest
from django.db import connection

from django_bolt.testing import TestClient

from missions.api import api

# Domain -> tenant schema mapping used throughout the test suite.
# These are created once per test run (schema DDL cannot be rolled back inside
# a transaction), and the Bolt TestClient sends the matching Host header so
# django-tenants' TenantMainMiddleware switches to the right schema.
TENANTS = {
    "acme": "acme.myapp.com",
    "beta": "beta.myapp.com",
}


def ensure_tenants():
    """(Re-)create tenant rows whose schema DDL already exists.

    TransactionTestCase (transaction=True tests) flushes all tables on
    teardown, which deletes the committed tenant/domain rows while the schemas
    themselves persist. Probes that rely on the tenants being present call this
    first; it is idempotent.
    """
    from tenants.models import Domain, Organization

    connection.set_schema_to_public()
    for schema_name, domain in TENANTS.items():
        if Organization.objects.filter(schema_name=schema_name).exists():
            continue
        tenant = Organization(schema_name=schema_name, name=schema_name.title())
        tenant.save()
        Domain.objects.create(domain=domain, tenant=tenant, is_primary=True)


@pytest.fixture(scope="session")
def tenants_created(django_db_setup, django_db_blocker):
    """Create tenant schemas in the test database once for the whole session."""
    with django_db_blocker.unblock():
        ensure_tenants()
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


def _create_spaceship(host: str) -> int:
    """Create a unique spaceship via the API on the given tenant host."""
    suffix = uuid.uuid4().hex[:6]
    with TestClient(api, base_url=f"http://{host}") as c:
        response = c.post(
            "/spaceships",
            json={"name": f"Falcon {suffix}", "call_sign": f"FLN-{suffix}"},
        )
    assert response.status_code == 200, response.text
    return response.json()["id"]


@pytest.fixture
def spaceship_id(client):
    """A spaceship belonging to the acme tenant."""
    return _create_spaceship(TENANTS["acme"])


@pytest.fixture
def beta_spaceship_id(beta_client):
    """A spaceship belonging to the beta tenant."""
    return _create_spaceship(TENANTS["beta"])
