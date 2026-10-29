# Space Mission Tracker (multi-tenant)

A django-tenants + django-bolt experiment where each real-world organization
gets its own isolated schema and subdomain to manage its space missions.

## Language

**Organization**:
The tenant itself: one row per real-world organization, owning exactly one
schema and one primary Domain.
_Avoid_: Client, tenant row, account

**Domain**:
The hostname a request arrives on; the source of truth for tenant routing.
Each Organization has exactly one, a subdomain of the main domain.

**Site**:
A derived mirror of an Organization's primary Domain in django.contrib.sites,
one per Organization with the same primary key. Never edited directly.
_Avoid_: site record, site entry

**Spaceship**:
The umbrella vehicle for missions. Belongs to an Organization implicitly, via
schema isolation.
_Avoid_: ship, vehicle, craft

**Mission**:
A voyage assigned to exactly one Spaceship. The ship can be reassigned while
the mission is Planned; once launched, the assignment is locked.

**Astronaut**:
A crew member flying exactly one Mission at a time.
