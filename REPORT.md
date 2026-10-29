# Technical Report: django-bolt 0.13.0 × django-tenants (contextvar patch)

**Audience:** maintainers of [django-bolt](https://bolt.farhana.li/) and
[django-tenants](https://github.com/django-tenants/django-tenants).

This report documents the effect of a **contextvar-based patch** to django-tenants
that carries per-request tenant state across the sync<->async thread boundary. It is
the final chapter in a sequence of evaluations:

1. Original REPORT.md (0.11.1) documented Probe A and Probe B bugs — but was
   unknowingly measured against a forked django-tenants that already masked them.
2. Switched to official PyPI `django-tenants==3.14.0` → the bugs **reproduced**.
3. The patched fork was installed → the bugs are **fixed** by the patch.
4. Current status: django-bolt **0.13.0** + the patched fork (now based on
   django-tenants **4.0.0**) → **30 passed, 0 warnings**. The secondary DB
   resource-leak finding is also resolved — by django-bolt 0.13.0 itself, not by
   the fork.

- Stack: Python 3.12, Django 6.1.1, django-bolt **0.13.0**, django-tenants
  **4.0.0 (patched fork, commit `33a712b`)**.
- Patch: `django_tenants/postgresql_backend/base.py` — per-request tenant state
  (`tenant`, `schema_name`, `include_public_schema`) is stored in a
  **ContextVar-backed, copy-on-write dict keyed by database alias** instead of
  plain thread-local instance attributes, so tenant state propagates across the
  sync<->async thread boundary (asgiref copies/restores the context) without
  leaking between concurrent requests.

---

## Current status

With django-bolt 0.13.0 and the patched fork, the full suite is
**30 passed, 0 warnings**:

| Probe | Result | Effect |
|-------|--------|--------|
| A — async ORM + schema switching | **PASS** (`schema_name='acme'`, writes land in the tenant schema) | **Fixed by the fork patch** |
| B — concurrent cross-tenant leakage | **PASS** (no leak, 30 acme + 30 beta concurrent probes) | **Fixed by the fork patch** |
| D — tenant-isolated media storage | Works | — |
| Secondary — Open DB connections / resource leak | **PASS, no warning** | **Resolved by django-bolt 0.13.0** |

---

## What the patch does, and why it solves the problem

### The core problem

django-tenants issue #1168: django-bolt spreads DB work across multiple threads.
`TenantMainMiddleware` sets tenant state on one thread, but the async ORM query
runs on a different threadpool thread (and concurrent requests run on more
threads still). Upstream django-tenants stored tenant state as **plain
thread-local instance attributes** on `DatabaseWrapper`, so:

- the query thread never saw the tenant the middleware selected (Probe A), and
- each thread's connection kept whatever `search_path` a *previous, concurrent*
  request for a different tenant had last set (Probe B's leakage).

### The patch (three commits, cumulative)

1. **ContextVar-backed tenant state** (original `ea132a93` commit) —
   `tenant`, `schema_name`, and `include_public_schema` became
   `@property`/`@setter` pairs reading/writing ContextVars, so tenant state
   propagates across asgiref's sync<->async boundaries (asgiref copies and
   restores the context) and is **per-task**: each request carries its own
   tenant to whatever thread runs the query, without leaking between concurrent
   requests. This directly fixes both the Probe A inconsistency and the Probe B
   leak mechanism.

2. **Removed the tenant-state reset** (`059ae66`) — `DatabaseWrapper.__init__`
   no longer resets state to `public`. A connection created lazily in the query
   thread inherits the tenant the middleware already resolved in the current
   context, instead of being silently reset and then querying the wrong schema.

3. **Per-alias state + stale search-path refresh** (`33a712b`, current commit) —
   - The state now lives in a **single ContextVar holding an immutable dict
     keyed by database alias** (`_TENANT_STATE_CONTEXTVAR` →
     `{"default": {"tenant": ..., "schema_name": ..., "include_public_schema": ...}}`),
     so multiple database connections (e.g. read replicas) can each have a
     different tenant active. The three earlier one-value-per-connection
     ContextVars were collapsed into this dict.
   - **Copy-on-write:** all writes go through `_set_tenant_state`, which copies
     the dict and publishes the new dict via `.set()` instead of mutating in
     place. This matters because a copied context shares the dict by reference —
     mutating it in place would leak tenant state into every other context that
     copied it (i.e. into concurrent requests/tasks). Publishing a new dict
     keeps each context isolated, which is what makes the concurrent Probe B
     guarantees airtight.
   - **Read-only default:** the default state is a `MappingProxyType`
     (`_DEFAULT_TENANT_STATE`), so accidental in-place mutation by external code
     raises `TypeError` instead of silently corrupting the defaults for every
     uninitialized alias.
   - **Stale search-path refresh:** with `limit_set_calls` enabled, the
     `_set_search_path` fast path used to skip re-executing
     `SET search_path` whenever the connection's cache was merely *filled in*.
     But the tenant can change (via the contextvars from another thread of the
     same request) while the connection instance still holds a stale cache from
     a previous tenant. The fast path now compares the cached
     `search_path_set_schemas` against the paths the **current** tenant state
     produces and re-executes `SET search_path` when they differ — so a reused
     connection is always re-scoped to the request's tenant.

The fork also adds `django_tenants/tests/test_async_tenant.py` (upstream test
suite for the async behavior).

---

## Probe A — Async ORM + schema switching (fixed)

Three tests cover it, all passing:

- `test_probe_a_async_schema_is_correct_per_tenant` — the async handler resolves
  the DB schema the `Host` header selects (`acme` → `acme`, `beta` → `beta`).
- `test_probe_a_async_path_schema_attribute` — both `current_schema()` and
  `connection.schema_name` read the tenant schema in the async path (the
  attribute previously stuck at `'public'`).
- `test_probe_a_async_orm_writes_into_tenant_schema` — creates done through
  async ORM (`apost`/`acreate`) land in the tenant's own schema and are
  invisible from the sibling tenant.

---

## Probe B — Concurrent cross-tenant schema leakage (fixed)

With 30 concurrent acme + 30 concurrent beta `/schema-debug` requests, no request
leaks across tenants. `test_probe_b_concurrent_cross_tenant_isolation` passes
with zero leaks (no longer xfail). **Fixed by the patch** — the copy-on-write,
per-task ContextVar state means each request re-scopes its own connection and
concurrent contexts cannot observe each other's tenant.

---

## Probe D — Tenant-isolated media storage (works)

Unchanged; per-tenant media directories remain correctly scoped
(`test_probe_d_patches_are_isolated_per_tenant`).

---

## Secondary finding — Open DB connections / resource leak (resolved by bolt 0.13.0)

The teardown warning

```
OperationalError('database "test_bolt_tenants" is being accessed by other users
DETAIL: There is 1 other session using the database.')
```

no longer appears. It was **fixed in django-bolt 0.13.0**, which
[lends the test's database connection to handler threads](https://github.com/dj-bolt/django-bolt/pull/315)
(so handler threads read/write inside the test transaction, exactly like
Django's own live-server tests) and closes pooled connections and worker lanes
on shutdown and after errors. No fork change was involved in this fix.

---

## Test results

### Current (django-bolt 0.13.0 + patched fork)

```
$ pytest -q
30 passed in 1.60s
```

### Comparison across configurations (historical, working-tree tests at the time)

| Configuration | Result |
|---------------|--------|
| 0.11.1 + PyPI django-tenants 3.14.0 | `2 failed, 16 passed, 1 warning` |
| 0.12.0-rc1 + PyPI django-tenants 3.14.0 | `2 failed, 16 passed, 1 warning` |
| 0.12.0-rc1 + patched fork (`ea132a93`) | `18 passed, 1 warning` |
| **0.13.0 + patched fork (`33a712b`, current)** | **`30 passed, 0 warnings`** |

---

## Conclusion

The contextvar patch to django-tenants is effective: it fixes both the async-path
`schema_name` inconsistency (Probe A) and the critical concurrent cross-tenant schema
leak (Probe B) in a django-bolt async stack. The current form (commit `33a712b`)
hardens the original idea — copy-on-write, per-alias, read-only state plus a stale
search-path refresh — at the cost of a small, localized change to
`postgresql_backend/base.py`. It is a strong candidate for upstreaming into
django-tenants. The DB connection resource leak (secondary finding) is resolved
separately by django-bolt 0.13.0's test-connection lending.

---

## Reproduction

`requirements.txt` pins the patched fork:
```
-e git+ssh://git@github.com/jucajuca/django-tenants.git@33a712b5502b79bccec09892f104e2bcfbade7b9#egg=django_tenants
```

```bash
pip install -r requirements.txt
python -m pytest -q   # 30 passed
```
