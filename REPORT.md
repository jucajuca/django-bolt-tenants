# Technical Report: django-bolt 0.12.0-rc1 × django-tenants (contextvar patch)

**Audience:** maintainers of [django-bolt](https://bolt.farhana.li/) and
[django-tenants](https://github.com/django-tenants/django-tenants).

This report documents the effect of a **contextvar-based patch** to django-tenants
that carries per-request tenant state across the sync<->async thread boundary. It is
the final chapter in a sequence of evaluations:

1. Original REPORT.md (0.11.1) documented Probe A and Probe B bugs — but was
   unknowingly measured against a forked django-tenants that already masked them.
2. Switched to official PyPI `django-tenants==3.14.0` → the bugs **reproduced**.
3. This report: reinstalled the patched fork
   (`ea132a93…`) → the bugs are **fixed** by the patch.

- Stack: Python 3.12, Django 6.1.1, django-bolt **0.12.0-rc1**, django-tenants
  **3.14.0 (patched fork, commit `ea132a93`)**.
- Patch: `django_tenants/postgresql_backend/base.py` — `tenant`, `schema_name`, and
  `include_public_schema` are now **ContextVar-backed properties** instead of plain
  thread-local instance attributes, so tenant state propagates across the
  sync<->async thread boundary (asgiref copies/restores the context).

---

## Summary of findings (patched fork)

| Probe | 0.11.1 + PyPI | 0.12.0-rc1 + PyPI | 0.12.0-rc1 + patched fork | Effect of patch |
|-------|---------------|-------------------|---------------------------|-----------------|
| A — async ORM + schema switching | FAIL (`schema_name='public'`) | FAIL | **PASS** (`schema_name='acme'`) | **Fixed** |
| B — concurrent cross-tenant leakage | FAIL (leaks to `beta`) | FAIL | **PASS** (no leak) | **Fixed** |
| D — tenant-isolated media storage | Works | Works | Works | — |
| Secondary — resource leak | Warning | Warning | Warning | Persists |

**Result:** With the patched fork, the full suite is **18 passed, 1 warning**. The
contextvar patch resolves both Probe A and Probe B. The DB resource-leak teardown
warning is unaffected and still present.

---

## What the patch does

The core problem (django-tenants issue #1168) is that django-bolt spreads DB work
across multiple threads: `TenantMainMiddleware` sets tenant state on one thread, but
the async ORM query runs on a different threadpool thread. Django-tenants stored
tenant state as **plain thread-local instance attributes** on `DatabaseWrapper`, so
the query thread never saw the tenant that the middleware selected.

The patch converts these to **ContextVar-backed properties**:

- `_TENANT_CONTEXTVAR`, `_SCHEMA_NAME_CONTEXTVAR`, `_INCLUDE_PUBLIC_SCHEMA_CONTEXTVAR`
- `tenant`, `schema_name`, `include_public_schema` become `@property`/`@setter` pairs
  reading/writing the ContextVars.
- `__init__` only resets to `public` if no tenant is already set (a connection created
  lazily in the query thread inherits the resolved tenant).
- `close()` clears the ContextVars so a reopened connection doesn't leak the previous
  request's tenant.

Because ContextVars propagate across asgiref's sync<->async boundaries (and are
per-task, not global), each request's tenant travels with the request to whatever
thread runs the query, without leaking between concurrent requests.

---

## Probe A — Async ORM + schema switching (fixed)

**Direct probe on 0.12.0-rc1 + patched fork:**
```
acme:  {'tenant_schema_name': 'acme', 'current_schema': 'acme'}
beta:  {'tenant_schema_name': 'beta',  'current_schema': 'beta'}
```

`connection.schema_name` now reads the correct tenant schema in the async path,
matching `current_schema()`. **Fixed by the patch.**

---

## Probe B — Concurrent cross-tenant schema leakage (fixed)

With 30 concurrent acme + 30 concurrent beta `/schema-debug` requests, no request
leaks across tenants. `test_probe_b_concurrent_cross_tenant_isolation` now **passes**
(no longer xfail). **Fixed by the patch.**

---

## Probe D — Tenant-isolated media storage (works)

Unchanged; per-tenant media directories remain correctly scoped.

---

## Secondary finding — Open DB connections / resource leak (persists)

The teardown warning is unaffected by the contextvar patch and still appears:
```
OperationalError('database "test_bolt_tenants" is being accessed by other users
DETAIL: There is 1 other session using the database.')
```

This is separate from the tenant-scoping fix — it concerns async-handler connections
not being closed before test teardown, and remains an open item for bolt's
`AsyncTestClient` connection management.

---

## Test results

### 0.12.0-rc1 + patched fork (current)

```
$ pytest -q
18 passed, 1 warning in 6.26s
```

### Comparison across configurations (working-tree tests)

| Configuration | Result |
|---------------|--------|
| 0.11.1 + PyPI django-tenants 3.14.0 | `2 failed, 16 passed, 1 warning` |
| 0.12.0-rc1 + PyPI django-tenants 3.14.0 | `2 failed, 16 passed, 1 warning` |
| 0.12.0-rc1 + patched fork (this report) | **`18 passed, 1 warning`** |

---

## Conclusion

The contextvar patch to django-tenants is effective: it fixes both the async-path
`schema_name` inconsistency (Probe A) and the critical concurrent cross-tenant schema
leak (Probe B) in a django-bolt async stack, at the cost of a small, localized change
to `postgresql_backend/base.py`. It is a strong candidate for upstreaming into
django-tenants. The DB connection resource leak (secondary finding) is a separate
issue that remains open.

---

## Reproduction

`requirements.txt` pins the patched fork:
```
-e git+ssh://git@github.com/jucajuca/django-tenants.git@ea132a9394ecc7ac7ffd78f2acd0bad6a6b19eed#egg=django_tenants
```

```bash
pip install -r requirements.txt
python -m pytest -q   # 18 passed, 1 warning
```
