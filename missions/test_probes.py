"""Probes for django-bolt 0.11.1 <-> django-tenants 3.14.0 feature clashes.

These tests are intentionally kept in the project (the user decided to keep the
probe routes and tests). Each test targets one area:

    Probe A - async ORM + schema switching
    Probe B - concurrent cross-tenant schema leakage
    Probe D - tenant-isolated media storage
"""

import asyncio
import os

import pytest
from django.conf import settings

from django_bolt.testing import AsyncTestClient

from missions.api import api

from conftest import TENANTS


# --------------------------------------------------------------------------- #
# Probe A: async ORM + schema switching
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_probe_a_async_schema_is_correct_per_tenant(client, beta_client):
    """The async handler must resolve the DB schema the Host header selects."""
    acme = client.get("/schema-debug")
    assert acme.status_code == 200
    assert acme.json()["tenant_schema_name"] == "acme"
    assert acme.json()["current_schema"] == "acme"

    beta = beta_client.get("/schema-debug")
    assert beta.status_code == 200
    assert beta.json()["tenant_schema_name"] == "beta"
    assert beta.json()["current_schema"] == "beta"


@pytest.mark.django_db(transaction=True)
def test_probe_a_async_path_schema_attribute(tenants_created):
    """Document the async path: the DB resolves to the tenant schema but
    django-tenants' in-memory connection.schema_name stays 'public'.

    FINDING: with the AsyncTestClient (handlers run in executor threads on their
    own connections), current_schema() is correct for a single request, but
    connection.schema_name reads 'public' for every request. Any django-tenants
    code that trusts connection.schema_name (e.g. model managers that filter by
    it) would mis-scope in the async path.
    """
    async def _run():
        async with AsyncTestClient(
            api, base_url=f"http://{TENANTS['acme']}"
        ) as acme:
            body = (await acme.get("/schema-debug")).json()
            return body

    body = asyncio.run(_run())
    # Functionally the right schema is used...
    assert body["current_schema"] == "acme"
    # ...but the django-tenants attribute is not set -> documented inconsistency.
    assert body["tenant_schema_name"] == "public"


@pytest.mark.django_db
def test_probe_a_async_orm_writes_into_tenant_schema(client, beta_client):
    """Creates done through async ORM (apost/acreate) must land in the tenant's
    own schema and be invisible from the sibling tenant."""
    client.post("/missions", json={"name": "Async Acme Mission"})
    beta_client.post("/missions", json={"name": "Async Beta Mission"})

    acme_list = client.get("/missions")
    acme_names = {m["name"] for m in acme_list.json()["missions"]}
    assert "Async Acme Mission" in acme_names
    assert "Async Beta Mission" not in acme_names

    beta_list = beta_client.get("/missions")
    beta_names = {m["name"] for m in beta_list.json()["missions"]}
    assert "Async Beta Mission" in beta_names
    assert "Async Acme Mission" not in beta_names


# --------------------------------------------------------------------------- #
# Probe B: concurrent cross-tenant schema leakage
# --------------------------------------------------------------------------- #
# FINDING (reproducible): under concurrent async requests, django-bolt +
# django-tenants leak the DB schema across tenants. acme requests resolved
# `current_schema` to `beta` ~3-4/15 times in every run, and
# `connection.schema_name` read `public` for every request in the async path.
# Root cause: TenantMainMiddleware runs via sync_to_async(thread_sensitive=True)
# on one thread (setting schema_name/search_path there), while the async ORM
# query runs on another thread whose connection.search_path was last set by a
# concurrent request for a different tenant. There is no per-request re-scoping
# of the actual connection the async query uses, so an acme request can run
# against beta's schema. Marked xfail to keep the suite green while recording it.
@pytest.mark.django_db(transaction=True)
@pytest.mark.xfail(
    strict=False,
    reason=(
        "django-bolt+django-tenants async concurrency leaks schema: async ORM "
        "query runs on a thread whose search_path was set by a concurrent "
        "request for another tenant; acme resolves current_schema to beta "
        "~3-4/15, and connection.schema_name reads 'public' in the async path."
    ),
)
def test_probe_b_concurrent_cross_tenant_isolation(tenants_created):
    """Fire acme and beta requests concurrently and assert no schema leaks.

    Uses AsyncTestClient (per-request handler threads each get their own DB
    connection, so rows must be committed -> transaction=True). We seed one
    mission into each schema, then run a burst of interleaved concurrent
    schema-debug probes and assert acme never resolves to beta's schema.
    """
    async def _run():
        async with AsyncTestClient(
            api, base_url=f"http://{TENANTS['acme']}"
        ) as acme, AsyncTestClient(api, base_url=f"http://{TENANTS['beta']}") as beta:
            # Seed a mission into each schema (committed via the API).
            assert (await acme.post("/missions", json={"name": "ACME-SECRET"})).status_code == 200
            assert (await beta.post("/missions", json={"name": "BETA-SECRET"})).status_code == 200

            async def acme_probe(n: int):
                r = await acme.get("/schema-debug")
                return "acme", n, r.status_code, r.json()

            async def beta_probe(n: int):
                r = await beta.get("/schema-debug")
                return "beta", n, r.status_code, r.json()

            results = await asyncio.gather(
                *(acme_probe(i) for i in range(30)),
                *(beta_probe(i) for i in range(30)),
            )

        for tenant, _, code, body in results:
            assert code == 200
            assert body["current_schema"] == tenant, (
                f"cross-tenant schema leak: {tenant} request resolved "
                f"current_schema={body['current_schema']!r}"
            )

    asyncio.run(_run())


@pytest.mark.django_db
def test_probe_d_patches_are_isolated_per_tenant(client, beta_client):
    """Patch uploads must be stored under per-tenant directories and each
    tenant must only ever see its own files."""
    acme_id = client.post("/missions", json={"name": "Acme Patch"}).json()["id"]
    beta_id = beta_client.post("/missions", json={"name": "Beta Patch"}).json()["id"]

    acme_up = client.post(
        f"/missions/{acme_id}/patch",
        files={"patch": ("acme.png", b"ACME-PATCH-CONTENT", "image/png")},
    )
    assert acme_up.status_code == 200
    assert acme_up.json()["tenant_schema"] == "acme"

    beta_up = beta_client.post(
        f"/missions/{beta_id}/patch",
        files={"patch": ("beta.png", b"BETA-PATCH-CONTENT", "image/png")},
    )
    assert beta_up.status_code == 200
    assert beta_up.json()["tenant_schema"] == "beta"

    media_root = str(settings.TENANT_MEDIA_ROOT)

    acme_dir = os.path.join(media_root, "acme", "patches")
    beta_dir = os.path.join(media_root, "beta", "patches")

    acme_files = os.listdir(acme_dir) if os.path.isdir(acme_dir) else []
    beta_files = os.listdir(beta_dir) if os.path.isdir(beta_dir) else []

    assert any("acme.png" in f for f in acme_files)
    assert any("beta.png" in f for f in beta_files)
    assert not any("beta.png" in f for f in acme_files)
    assert not any("acme.png" in f for f in beta_files)

    # The stored path returned to acme must be inside the acme tenant dir only.
    assert os.path.commonpath([acme_up.json()["path"], acme_dir]) == acme_dir
    assert os.path.commonpath([beta_up.json()["path"], beta_dir]) == beta_dir
