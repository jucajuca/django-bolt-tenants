# Technical Report: django-bolt 0.12.0-rc1 × django-tenants 3.14.0 — Re-evaluation

**Audience:** maintainers of [django-bolt](https://bolt.farhana.li/) and
[django-tenants](https://github.com/django-tenants/django-tenants).

This report re-evaluates the findings from the original REPORT.md (django-bolt 0.11.1)
after upgrading to **django-bolt 0.12.0-rc1** with official PyPI `django-tenants==3.14.0`.

**Key discovery:** The original REPORT.md findings were obtained using a **forked version
of django-tenants** from a git repository, not the official PyPI release. The fork
contained an unknown fix that masked the bugs. When switching to official PyPI
`django-tenants==3.14.0`, the bugs documented in the original report now reproduce
correctly.

- Stack: Python 3.12, Django 6.1.1, django-bolt **0.12.0-rc1**, django-tenants **3.14.0**
  (PyPI), PostgreSQL.
- Tenants: `acme` (Host `acme.localhost`) and `beta` (Host `beta.localhost`).

---

## Summary of findings

| Probe | Original REPORT.md | 0.11.1 + PyPI django-tenants | 0.12.0-rc1 + PyPI django-tenants | Change |
|-------|-------------------|------------------------------|----------------------------------|--------|
| A — async ORM + schema switching | `connection.schema_name` = `'public'` | **FAILS** | **FAILS** | No change |
| B — concurrent cross-tenant leakage | Leaks ~3-4/15 requests | **FAILS** | **FAILS** | No change |
| D — tenant-isolated media storage | Works | Works | Works | — |
| Secondary — resource leak | Warning | Warning | Warning | Persists |

**Verdict:** 0.12.0-rc1 produces **identical results** to 0.11.1 with official PyPI
django-tenants. The bugs documented in the original REPORT.md **do reproduce** on both
versions. The RC does not improve or regress any of the documented issues.

---

## Detailed comparison

### Probe A — Async ORM + schema switching

**Direct probe on 0.12.0-rc1:**
```
acme:  {'tenant_schema_name': 'public', 'current_schema': 'acme'}
beta:  {'tenant_schema_name': 'public', 'current_schema': 'beta'}
```

**Finding:** `connection.schema_name` reads `'public'` in the async path, even though
`current_schema()` correctly returns the tenant schema. This matches the original
REPORT.md finding. **Bug is present on both 0.11.1 and 0.12.0-rc1.**

---

### Probe B — Concurrent cross-tenant schema leakage

**Finding:** Under concurrent async requests, acme requests resolve `current_schema()`
to `beta` — a real cross-tenant data leak. This matches the original REPORT.md finding.

**Test result:**
```
AssertionError: cross-tenant schema leak: acme request resolved current_schema='beta'
```

**Bug is present on both 0.11.1 and 0.12.0-rc1.**

---

### Probe D — Tenant-isolated media storage

**Finding:** Still works on both versions. No regression.

---

### Secondary finding — Open DB connections / resource leak

**Finding:** The warning persists on both versions:
```
OperationalError('database "test_bolt_tenants" is being accessed by other users')
```

---

## Test results

### 0.11.1 + PyPI django-tenants 3.14.0

```
$ pytest -q
2 failed, 16 passed, 1 warning in 6.87s

FAILED: test_probe_a_async_path_schema_attribute
FAILED: test_probe_b_concurrent_cross_tenant_isolation
```

### 0.12.0-rc1 + PyPI django-tenants 3.14.0

```
$ pytest -q
2 failed, 16 passed, 1 warning in 6.70s

FAILED: test_probe_a_async_path_schema_attribute
FAILED: test_probe_b_concurrent_cross_tenant_isolation
```

### Original committed tests (HEAD) on 0.12.0-rc1

```
$ pytest -q -rx
4 passed, 1 xfailed, 1 warning in 6.53s

XFAIL: test_probe_b_concurrent_cross_tenant_isolation
```

---

## Key insight: Fork vs PyPI

The original REPORT.md was written using a **forked django-tenants** from:
```
-e git+ssh://git@github.com/jucajuca/django-tenants.git@ea132a93...#egg=django_tenants
```

This forked version contained an unknown fix that prevented the bugs from reproducing.
When switching to the official PyPI release (`django-tenants==3.14.0`), all documented
bugs correctly reproduce.

The `requirements.txt` has been updated to use the official PyPI version:
```
django-tenants==3.14.0
```

---

## Reproduction

```bash
# Install dependencies
pip install -r requirements.txt

# Run tests
python -m pytest -q
```

Expected: `2 failed, 16 passed, 1 warning` on both 0.11.1 and 0.12.0-rc1.
