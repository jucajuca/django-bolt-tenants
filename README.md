# Space Mission Tracker

A [Django-Bolt](https://bolt.farhana.li/) experiment implementing the "Space Mission Tracker" Quick Start guide.

This is an **experiment only** — see [AGENTS.md](./AGENTS.md). The code, database, and configuration can be changed or deleted at any time.

## Stack

- Python 3.12
- Django 6.1
- django-bolt 0.11
- django-debug-toolbar
- pytest + pytest-django

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install django django-bolt django-debug-toolbar pytest pytest-django
```

## Run the project

Apply migrations and start the Bolt dev server (with auto-reload, required for the debug toolbar):

```bash
python manage.py migrate
python manage.py runbolt --dev
```

Then open:

- API root: <http://127.0.0.1:8000/>
- API docs (Scalar): <http://127.0.0.1:8000/docs>
- Swagger docs: <http://127.0.0.1:8000/docs/swagger>
- Dashboard (HTML, shows the debug toolbar): <http://127.0.0.1:8000/dashboard>

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
