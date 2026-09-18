# AGENTS.md

## This is an experiment — treat everything as disposable

This repository is a **throwaway experiment** for learning and evaluating
[Django-Bolt](https://bolt.farhana.li/). Nothing here is production code.

- **Code can be deleted or changed** freely. Refactor, rewrite, or remove any
  file, module, endpoint, or configuration without concern.
- **The database can be reset (nuked) at any time.** `db.sqlite3` is a local
  dev artifact. Feel free to delete it and re-run `python manage.py migrate`.
  The migrations in `missions/migrations/` define the schema from scratch.
- **The virtualenv can be recreated.** `.venv` is disposable; reinstall
  dependencies from `README.md` if needed.
- **Do not worry about git history, back-compat, or stable APIs.** There are no
  consumers of this code and no requirements to preserve.
- **No strict conventions.** Follow Django/django-bolt best practices as a guide,
  but prioritize a working, self-contained demo over rigor.

The goal is to explore django-bolt's features (APIs, serializers, response
types, middleware, debug-toolbar integration, testing) quickly and safely.
