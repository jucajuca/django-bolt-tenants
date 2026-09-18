# Technical Report: django-bolt 0.11.1 × django-tenants 3.14.0 Feature Clashes

**Audience:** maintainers of [django-bolt](https://bolt.farhana.li/) and
[django-tenants](https://github.com/django-tenants/django-tenants).

This report documents an empirical probing of the integration between the two
libraries in an async HTTP stack. Everything was observed by running real
requests (sync and async) and instrumenting thread/connection state. This is an
experiment; the full repro is in `missions/` (`api.py`, `test_probes.py`,
`async_tenant_middleware.py`) and `myproject/settings.py`.

- Stack: Python 3.12, Django 6.1.1, django-bolt 0.11.1, django-tenants 3.14.0,
  django-debug-toolbar 8.0.0, pytest 9.1.1 / pytest-django 4.14.0,
  PostgreSQL (backend `django_tenants.postgresql_backend`).
- Tenants: `acme` (Host `acme.localhost`) and `beta` (Host `beta.localhost`).
- Two test clients:
  - **sync `TestClient`** — Django's shared-connection request path.
  - **`AsyncTestClient`** — django-bolt's async-native transport; handlers run
    on executor threads, each with its own DB connection.

---

## Summary of findings

| Probe | Finding | Severity |
|-------|---------|----------|
| A — async ORM + schema switching | `connection.schema_name` reads `'public'` in the async path even though the DB resolves to the correct tenant schema | **Bug** |
| B — concurrent cross-tenant schema leakage | A request for tenant A resolves `current_schema()` to tenant B's schema under concurrency | **Bug, data-isolation-critical** |
| D — tenant-isolated media storage | Per-tenant media directories are correctly scoped | Works |
| Secondary — resource leak | Async-client handlers leave open DB connections ("database is being accessed by other users") | Resource leak |

---

## Probe A — Async ORM + schema switching

**Route:** `GET /schema-debug` returns two values:
- `tenant_schema_name` — django-tenants' in-memory `connection.schema_name`.
- `current_schema` — the database's real answer to `SELECT current_schema()`
  (executed inside a `@sync_to_async` helper).

**Observation:**
- **Sync client:** `tenant_schema_name` and `current_schema` both resolve
  correctly to `acme` / `beta`.
- **Async client (`AsyncTestClient`):** `current_schema()` correctly returns
  the tenant schema (e.g. `acme`), **but `connection.schema_name` reads
  `'public'` for every request.**

**Why:** in the async path the sync `TenantMainMiddleware` runs via
`sync_to_async(thread_sensitive=True)` on one thread and calls
`connection.set_tenant(tenant)`, which sets `schema_name` on *that thread's*
thread-local connection (`asgiref.Local`). The async handler's
`@sync_to_async`/async-ORM DB work runs on a *different* thread whose own
connection has `schema_name` left at `'public'`.

**Impact for django-tenants:** any code that trusts the in-memory
`connection.schema_name` attribute — e.g. model managers, `TenantModel` filters,
anything branching on the schema name — will mis-scope in the async path. The
real `SET search_path` happens to be correct (hence `current_schema()` is right),
but the attribute the library exposes is not.

**For bolt:** consider whether `connection.schema_name` should be made
thread-consistent with the actual connection that executed the query, or whether
the async-path contract should be documented so tenant libraries know not to
trust that attribute.

---

## Probe B — Concurrent cross-tenant schema leakage (critical)

**Test:** `test_probe_b_concurrent_cross_tenant_isolation` fires 30 acme and 30
beta `/schema-debug` probes concurrently via `asyncio.gather` over two
`AsyncTestClient` instances, then asserts every request resolved
`current_schema()` to its own tenant.

**Observation:** on **every** run, an acme request resolved `current_schema()` to
`beta` roughly **3–4 times out of 15**. This is a real, reproducible
cross-tenant schema leak — not a test artifact. (It is marked `xfail(strict=False)`
so the suite stays green while recording the defect.)

**Root cause:** the async ORM query for a given request runs on a thread whose
`search_path` was last set by a *concurrent request for a different tenant*.
There is no per-request re-scoping of the actual connection the async query
uses. Specifically:

1. `TenantMainMiddleware` (hook-based) is wrapped by bolt in
   `sync_to_async(thread_sensitive=True)`, so it runs on the asgiref main thread
   and calls `set_tenant()` on *that* thread's connection.
2. The async handler's DB work runs on threadpool threads, each with its own
   thread-local connection.
3. Django-tenants scopes via a single `connection.schema_name` + a lazy
   `SET search_path` issued on first cursor use. Under concurrency, a threadpool
   thread may have last executed `SET search_path = beta` for a previous beta
   request, then run the next acme request's query against `beta`'s schema.

Because `search_path` is a session-level state on the underlying connection and
connections are not re-scoped per request before the query executes, an acme
request can physically run against beta's schema — returning the wrong tenant's
rows, and worse, a cross-tenant `INSERT`/`UPDATE` would write into the wrong
tenant's schema.

**Attempted fix (falsified):** an async `__call__`-only middleware
(`missions/async_tenant_middleware.py`) that re-scopes the connection from inside
the async chain was written to replace `TenantMainMiddleware`. It **does not
work**: the middleware sets the tenant on the event-loop thread, but async ORM
and `@sync_to_async` work still hop to threadpool threads, so a single middleware
thread cannot scope the query thread. With it active, even a single async request
regressed to `current_schema() == 'public'`, and `POST /missions` failed with
`django.db.utils.ProgrammingError: relation "missions_mission" does not exist`.

**What a real fix needs:** scope the connection *inside* the thread that runs
each DB operation, not in a per-request middleware. Options for the two libraries
to consider:

- **django-tenants:** a `connection_created`/per-thread hook that re-applies the
  current request's `search_path` when a threadpool connection is first used, or
  an explicit "begin request" API callable from async handlers before touching
  the ORM.
- **django-bolt:** a way to dispatch async DB operations in a
  thread-sensitive manner so all DB work for one request shares a single
  connection, or explicit support for wiring an async tenant middleware so the
  scoping and the query run on the same thread.

---

## Probe D — Tenant-isolated media storage (works)

Patch uploads (`POST /missions/{id}/patch`) write to
`{TENANT_MEDIA_ROOT}/{connection.schema_name}/patches/` instead of a hardcoded
shared directory. `test_probe_d_patches_are_isolated_per_tenant` verifies:

- acme and beta uploads land in separate directories
  (`media/tenant_patches/acme/patches/`, `media/tenant_patches/beta/patches/`).
- neither tenant's files appear in the other's directory.
- the returned path is always inside the requesting tenant's own directory.

**Note:** this probe reads `connection.schema_name` to build the path. On the
**sync** client this is correct, so isolation holds there. In the async path,
`connection.schema_name` reads `'public'` (Probe A), so any async upload would
fall into the `public/` bucket — an indirect consequence of Probe A that must be
fixed before tenant-media isolation can be relied on in the async path.

---

## Secondary finding — Open DB connections / resource leak

Async-client handlers leave open DB connections. pytest-django warns during
teardown:

```
OperationalError('database "test_bolt_tenants" is being accessed by other users
DETAIL: There is 1 other session using the database.')
```

This is a resource leak, not a test failure — connections created on executor
threads are not closed/returned before the test DB is torn down. Worth
addressing in bolt's `AsyncTestClient` (and its production async connection
management) to avoid exhausting PostgreSQL connections under load.

---

## Reproduction pointers

- `missions/api.py` — `/schema-debug` route; tenant media upload
  (`upload_mission_patch`); the `DJANGO_MIDDLEWARE` chain starting with
  `django_tenants.middleware.main.TenantMainMiddleware`.
- `missions/test_probes.py` — Probe A (sync + async discrepancy), Probe B
  (concurrency leak, `xfail`), Probe D (media isolation).
- `missions/async_tenant_middleware.py` — falsified async fix, kept as evidence.
- `myproject/settings.py` — `SHARED_APPS`/`TENANT_APPS`, `TenantSyncRouter`,
  `TENANT_MEDIA_ROOT`.

Run with: `python -m pytest -q` (expect `17 passed, 1 xfailed`).
