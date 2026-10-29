"""Keep django.contrib.sites in sync with tenant Domains.

Domain is the source of truth for tenant routing; Site is a derived mirror.
Because each Organization owns exactly one primary Domain, there is exactly
one Site per Organization, created with ``Site.pk == Organization.id``:

- Deterministic lookup: ``Site.objects.get(pk=tenant.pk)``.
- Rename drift is impossible: when a Domain's hostname changes, the same Site
  row (matched by pk) is updated in place rather than duplicated.
- Only primary Domains are mirrored, so alias domains would never clobber a
  tenant's Site.

Tenant/schema deletion cascades through Domain, so the post_delete hook on
Domain removes the mirror Site automatically.
"""

from django.contrib.sites.models import Site
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from tenants.models import Domain


@receiver(post_save, sender=Domain)
def sync_site_from_domain(sender, instance: Domain, **kwargs):
    """Mirror the primary Domain into a Site keyed by the tenant's id."""
    if not instance.is_primary:
        return
    Site.objects.update_or_create(
        pk=instance.tenant_id,
        defaults={"domain": instance.domain, "name": instance.domain},
    )


@receiver(post_delete, sender=Domain)
def delete_site_for_domain(sender, instance: Domain, **kwargs):
    """Remove the mirror Site when the tenant's primary Domain disappears."""
    if not instance.is_primary:
        return
    Site.objects.filter(pk=instance.tenant_id).delete()
