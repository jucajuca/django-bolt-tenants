from django.db import models

from django_tenants.models import DomainMixin, TenantMixin


class Organization(TenantMixin):
    """The tenant itself: one row per real-world organization.

    Renamed from django-tenants' default ``Client``. Each Organization owns
    exactly one schema and one primary Domain; ownership of tenant-scoped data
    (spaceships, missions, astronauts) is implicit via schema isolation.
    """

    name = models.CharField(max_length=100)
    created_on = models.DateField(auto_now_add=True)

    auto_create_schema = True

    def __str__(self):
        return self.name


class Domain(DomainMixin):
    pass
