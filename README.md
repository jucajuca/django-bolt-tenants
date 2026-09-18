# Space Mission Tracker

A [Django-Bolt](https://bolt.farhana.li/) experiment implementing the "Space Mission Tracker" Quick Start guide.

This is an **experiment only** — see [AGENTS.md](./AGENTS.md). The code, database, and configuration can be changed or deleted at any time.

## Stack

- Python 3.12
- Django 6.1
- django-bolt 0.11
- django-debug-toolbar
- **django-tenants 3.14** (multi-tenant schemas)
- PostgreSQL (required by django-tenants)
- pytest + pytest-django

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install django django-bolt django-debug-toolbar django-tenants psycopg2-binary pytest pytest-django
```

### PostgreSQL

django-tenants uses one PostgreSQL schema per tenant, so it cannot run on SQLite.
Point `DATABASES.default` in `myproject/settings.py` at a running PostgreSQL
instance (see the `ENGINE = django_tenants.postgresql_backend` setting).

For this experiment a local Docker container is used:

```bash
docker run -d --name django-tenants-pg \
  -e POSTGRES_USER=bolt -e POSTGRES_PASSWORD=bolt -e POSTGRES_DB=bolt_tenants \
  -p 127.0.0.1:5433:5432 postgres:15-alpine
```

## Run the project

Apply migrations (shared/public schema) and create at least the `public` tenant
plus the tenant(s) your Bolt routes will resolve against. Then start the Bolt
dev server (with auto-reload, required for the debug toolbar):

```bash
python manage.py migrate_schemas --shared
python manage.py runbolt --dev
```

> `django_tenants` requires a `public` tenant with a domain record to exist.
> See `scripts/create_tenants.py` (or the shell commands in the session) to seed
> tenants like `public`, `acme` (`acme.localhost`) and `beta` (`beta.localhost`).

To run on a different port, e.g. `9080`:

```bash
python manage.py runbolt --dev --port 9080
```

The Bolt app is now **multi-tenant**: it resolves the tenant from the request
`Host` header and switches the DB schema via `TenantMainMiddleware`. Open a
tenant host (after adding `acme.localhost` etc. to `/etc/hosts`):

- Acme API root: <http://acme.localhost:8000/>
- API docs (Scalar): <http://acme.localhost:8000/docs>
- Swagger docs: <http://acme.localhost:8000/docs/swagger>
- Dashboard (HTML, shows the debug toolbar): <http://acme.localhost:8000/dashboard>

Requests to a host with no matching tenant return `404`.

### Example endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/missions` | List missions |
| POST | `/missions` | Create a mission |
| GET | `/missions/{id}` | Get a mission |
| PUT | `/missions/{id}` | Update a mission |
| DELETE | `/missions/{id}` | Delete a mission |
| GET | `/missions/{id}/classified` | Classified info (needs `X-Clearance-Level` header, e.g. `top-secret`) |
| GET | `/missions/{id}/log` | Plain-text mission log |
| POST | `/missions/{id}/patch` | Upload a mission patch image |
| POST | `/missions/{id}/astronauts` | Assign an astronaut (form) |
| GET | `/missions/{id}/astronauts` | List astronauts |
| GET | `/dashboard` | HTML dashboard |
| GET | `/go` | Redirect to `/dashboard` |

## Run the tests

```bash
python -m pytest
```

The test config lives in `pytest.ini` (`DJANGO_SETTINGS_MODULE = myproject.settings`).
`conftest.py` creates two tenant schemas (`acme`/`acme.localhost` and
`beta`/`beta.localhost`) once per session in the test database, and the Bolt
test clients send the matching `Host` header. A dedicated test
(`test_missions_are_isolated_per_tenant`) verifies mission data is isolated
across tenant schemas.
