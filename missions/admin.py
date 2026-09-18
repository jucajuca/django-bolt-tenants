from django.contrib import admin

from missions.models import Astronaut, Mission


@admin.register(Mission)
class MissionAdmin(admin.ModelAdmin):
    list_display = ("name", "status", "launch_date")
    list_filter = ("status",)
    search_fields = ("name", "description")
    list_editable = ("status",)
    fieldsets = (
        (None, {"fields": ("name", "status", "launch_date", "description")}),
        ("Patch", {"fields": ("patch_image",), "classes": ("collapse",)}),
    )


@admin.register(Astronaut)
class AstronautAdmin(admin.ModelAdmin):
    list_display = ("name", "role", "mission")
    list_filter = ("role", "mission")
    search_fields = ("name", "role", "mission__name")
