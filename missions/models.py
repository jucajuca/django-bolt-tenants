from django.core.exceptions import ValidationError
from django.db import models


class Spaceship(models.Model):
    """Umbrella for missions: every mission is assigned exactly one ship."""

    name = models.CharField(max_length=100)
    call_sign = models.CharField(max_length=20, unique=True)

    def __str__(self):
        return f"{self.name} [{self.call_sign}]"


class Mission(models.Model):
    STATUS_CHOICES = [
        ("planned", "Planned"),
        ("active", "Active"),
        ("completed", "Completed"),
        ("aborted", "Aborted"),
    ]

    name = models.CharField(max_length=100)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="planned")
    launch_date = models.DateTimeField(null=True, blank=True)
    description = models.TextField(blank=True)
    patch_image = models.CharField(max_length=255, blank=True)
    spaceship = models.ForeignKey(
        Spaceship, on_delete=models.PROTECT, related_name="missions"
    )

    def clean(self):
        # A mission's ship is reassignable until launch: once the mission has
        # left 'planned', the assignment is locked.
        if self.pk and self.status != "planned":
            original = Mission.objects.filter(pk=self.pk).first()
            if original and original.spaceship_id != self.spaceship_id:
                raise ValidationError(
                    {"spaceship": "Cannot reassign a spaceship after launch"}
                )
        super().clean()

    def __str__(self):
        return self.name


class Astronaut(models.Model):
    name = models.CharField(max_length=100)
    role = models.CharField(max_length=50)
    mission = models.ForeignKey(
        Mission, on_delete=models.CASCADE, related_name="astronauts"
    )

    def __str__(self):
        return f"{self.name} ({self.role})"
