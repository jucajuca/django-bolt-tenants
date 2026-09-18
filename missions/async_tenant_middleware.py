"""Async-aware tenant middleware probe (FALSIFIED - kept as evidence).

Probe B fix mechanism (attempted): replace django-tenants' sync
``TenantMainMiddleware`` (hook-based, wrapped by django-bolt in
``sync_to_async(thread_sensitive=True)`` so it runs on a thread separate from
the async handler) with an **async ``__call__``-only** middleware that re-scopes
the DB connection from inside the async chain.

RESULT: **this mechanism does NOT fix the concurrent cross-tenant schema leak,
and it regresses even single-request scoping.** The middleware sets the tenant on
the event-loop/async-chain thread's connection, but Django's async ORM
(``Mission.objects.acreate``, ``aget``) and ``@sync_to_async`` handlers run on
arbitrary threadpool threads (``sync_to_async(thread_sensitive=False)``) with
their OWN thread-local connections. A single middleware thread therefore cannot
scope the thread that actually executes the query.

Empirically confirmed (instrumented): with this middleware active, a single async
request resolved ``current_schema()`` to ``public`` (regressed from ``acme``),
and ``POST /missions`` failed with
``ProgrammingError: relation "missions_mission" does not exist`` because the
ORM's INSERT ran on a public-scoped threadpool connection.

Root cause of Probe B is thus inherent to django-bolt's async dispatch: it
spreads DB work across multiple threads, while django-tenants scopes per-request
via a single thread-local ``connection.schema_name`` + lazy ``SET search_path``.
No per-request middleware (sync or async) can scope all the threads that run
queries under concurrency; a real fix must scope the connection *inside* the
thread that runs each DB operation (e.g. connection_created signal keyed to the
thread's request context, or thread-sensitive DB dispatch).

This file is retained purely as documentation of the failed fix mechanism.
"""

from asgiref.sync import sync_to_async
from django.db import connection

from django_tenants.utils import remove_www, get_tenant_domain_model
from django_bolt.middleware.django_adapter import DjangoMiddleware


class AsyncTenantMiddlewareDjangoWrapper(DjangoMiddleware):
    """DjangoMiddleware wrapper that correctly marks an async __call__-only
    middleware as async.

    django-bolt's DjangoMiddleware.__init__ sets _middleware_is_async via
    iscoroutinefunction(instance), which asgiref evaluates as False for a plain
    async __call__ on an instance (it only inspects the unbound function). That
    makes the async middleware fall into the sync branch and crash. Override the
    detection to inspect the class's __call__ instead."""

    def _create_middleware_instance(self, get_response):
        super()._create_middleware_instance(get_response)
        from asgiref.sync import iscoroutinefunction

        if self.middleware_class is not None:
            self._middleware_is_async = iscoroutinefunction(self.middleware_class.__call__)


class AsyncTenantMiddleware:
    """Async ``__call__``-only middleware that resolves the tenant from the
    Host header and scopes the DB connection to that tenant's schema."""

    def __init__(self, get_response):
        self.get_response = get_response

    @staticmethod
    def hostname_from_request(request):
        return remove_www(request.get_host().split(":")[0])

    async def __call__(self, request):
        connection.set_schema_to_public()
        hostname = self.hostname_from_request(request)
        domain_model = get_tenant_domain_model()

        @sync_to_async
        def _resolve_tenant(hostname):
            return domain_model.objects.select_related("tenant").get(domain=hostname).tenant

        tenant = await _resolve_tenant(hostname)
        connection.set_tenant(tenant)
        try:
            return await self.get_response(request)
        finally:
            connection.set_schema_to_public()
