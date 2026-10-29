from __future__ import annotations

import asyncio
import os
from datetime import datetime
from typing import Annotated, Literal

from msgspec import Meta

from asgiref.sync import sync_to_async
from django.conf import settings
from django.db import connection
from django_bolt import BoltAPI, Request
from django_bolt.exceptions import HTTPException, NotFound
from django_bolt.openapi import OpenAPIConfig
from django_bolt.param_functions import File, Form, Header, Query
from django_bolt.responses import HTML, PlainText, Redirect
from django_bolt.serializers import Serializer, field, field_validator
from django_bolt.shortcuts import render

from missions.models import Astronaut, Mission, Spaceship

# django-tenants must resolve the tenant (and switch the DB schema) before any
# other Django middleware runs, so it goes first in the chain. (An earlier probe
# tried replacing TenantMainMiddleware with an async __call__-only middleware;
# it was falsified — a per-request middleware cannot scope the thread-local
# connections used by the threads that run the queries. The real fix was the
# contextvar-backed tenant state in the django-tenants fork, requirements.txt.)
# The standard sync TenantMainMiddleware (via DjangoMiddlewareStack) remains.
DJANGO_MIDDLEWARE = ["django_tenants.middleware.main.TenantMainMiddleware"]

if "debug_toolbar" in settings.INSTALLED_APPS:
    DJANGO_MIDDLEWARE.append("debug_toolbar.middleware.DebugToolbarMiddleware")

api = BoltAPI(
    openapi_config=OpenAPIConfig(
        title="Space Mission Tracker",
        description="NASA-style mission control API",
        version="1.0.0",
    ),
    django_middleware=DJANGO_MIDDLEWARE,
)

if "debug_toolbar" in settings.INSTALLED_APPS:
    api.mount_django("/__debug__", clear_root_path=True)


class CreateSpaceship(Serializer):
    name: Annotated[str, Meta(min_length=1, max_length=100)]
    call_sign: Annotated[str, Meta(min_length=1, max_length=20)]


class SpaceshipResponse(Serializer):
    id: int
    name: str
    call_sign: str


class CreateMission(Serializer):
    name: Annotated[str, Meta(min_length=1, max_length=100)]
    spaceship: int
    description: Annotated[str, Meta(max_length=500)] = ""
    launch_date: datetime | None = None

    @field_validator("name")
    def validate_name(cls, value):
        if value.lower().startswith("test"):
            raise ValueError("Mission name cannot start with 'test'")
        return value


class UpdateMission(Serializer):
    name: Annotated[str, Meta(min_length=1, max_length=100)] | None = None
    status: Literal["planned", "active", "completed", "aborted"] | None = None
    spaceship: int | None = None
    description: Annotated[str, Meta(max_length=500)] | None = None


class MissionResponse(Serializer):
    id: int
    name: str
    status: str
    launch_date: datetime | None = None
    description: str = ""
    spaceship_id: int
    spaceship_name: str = field(source="spaceship.name")


class MissionListResponse(Serializer):
    missions: list[MissionResponse]
    count: int


class MissionCreatedResponse(Serializer):
    id: int
    name: str
    status: str
    message: str


class MissionFilters(Serializer):
    status: Literal["planned", "active", "completed", "aborted"] | None = None
    limit: Annotated[int, Meta(ge=1, le=100)] = 10


class CreateAstronaut(Serializer):
    name: Annotated[str, Meta(min_length=1, max_length=100)]
    role: Annotated[str, Meta(min_length=1, max_length=50)]

    @field_validator("role")
    def validate_role(cls, value):
        valid_roles = [
            "Commander",
            "Pilot",
            "Mission Specialist",
            "Flight Engineer",
            "Payload Specialist",
        ]
        if value not in valid_roles:
            raise ValueError(f"Role must be one of: {', '.join(valid_roles)}")
        return value


class AstronautResponse(Serializer):
    id: int
    name: str
    role: str
    mission_id: int


class AstronautCreatedResponse(Serializer):
    id: int
    name: str
    role: str
    mission: str = field(source="mission.name")


class AstronautListResponse(Serializer):
    mission: str
    astronauts: list[AstronautResponse]


@api.get("/", tags=["status"])
async def mission_control_status():
    return {"status": "operational", "message": "Mission Control Online"}


@api.get("/spaceships", tags=["spaceships"])
async def list_spaceships() -> list[SpaceshipResponse]:
    return [await SpaceshipResponse.afrom_model(ship) async for ship in Spaceship.objects.all()]


@api.post("/spaceships", tags=["spaceships"])
async def create_spaceship(data: CreateSpaceship) -> SpaceshipResponse:
    try:
        ship = await Spaceship.objects.acreate(
            name=data.name, call_sign=data.call_sign
        )
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail=f"Could not create spaceship: {exc}"
        ) from exc
    return await SpaceshipResponse.afrom_model(ship)


@api.get("/spaceships/{spaceship_id}", tags=["spaceships"])
async def get_spaceship(spaceship_id: int) -> SpaceshipResponse:
    try:
        ship = await Spaceship.objects.aget(id=spaceship_id)
    except Spaceship.DoesNotExist as exc:
        raise NotFound(detail=f"Spaceship {spaceship_id} not found") from exc
    return await SpaceshipResponse.afrom_model(ship)


@api.get("/schema-debug", tags=["probe"])
async def schema_debug():
    """Probe A: report which DB schema this request actually resolves to.

    Exposes both django-tenants' in-memory ``connection.schema_name`` and the
    database's real ``current_schema()`` so we can confirm the async ORM and
    raw queries run against the tenant the Host header selected.
    """

    @sync_to_async
    def _current_schema() -> str:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_schema()")
            return cursor.fetchone()[0]

    real_schema = await _current_schema()
    return {
        "tenant_schema_name": getattr(connection, "schema_name", None),
        "current_schema": real_schema,
    }


@api.get("/missions", tags=["missions"])
async def list_missions(filters: Annotated[MissionFilters, Query()]) -> MissionListResponse:
    queryset = Mission.objects.select_related("spaceship")
    if filters.status:
        queryset = queryset.filter(status=filters.status)

    mission_tasks = [
        MissionResponse.afrom_model(mission)
        async for mission in queryset[: filters.limit]
    ]
    missions = list(await asyncio.gather(*mission_tasks))
    return MissionListResponse(missions=missions, count=len(missions))


@api.get("/missions/{mission_id}", tags=["missions"])
async def get_mission(mission_id: int) -> MissionResponse:
    try:
        mission = await Mission.objects.select_related("spaceship").aget(id=mission_id)
        return await MissionResponse.afrom_model(mission)
    except Mission.DoesNotExist as exc:
        raise NotFound(detail=f"Mission {mission_id} not found") from exc


@api.post("/missions", tags=["missions"])
async def create_mission(mission: CreateMission) -> MissionCreatedResponse:
    try:
        ship = await Spaceship.objects.aget(id=mission.spaceship)
    except Spaceship.DoesNotExist as exc:
        raise NotFound(detail=f"Spaceship {mission.spaceship} not found") from exc

    new_mission = await Mission.objects.acreate(
        name=mission.name,
        description=mission.description,
        launch_date=mission.launch_date,
        status="planned",
        spaceship=ship,
    )
    return MissionCreatedResponse(
        id=new_mission.id,
        name=new_mission.name,
        status=new_mission.status,
        message="Mission created successfully",
    )


@api.put("/missions/{mission_id}", tags=["missions"])
async def update_mission(mission_id: int, data: UpdateMission) -> MissionResponse:
    try:
        mission = await Mission.objects.aget(id=mission_id)
    except Mission.DoesNotExist as exc:
        raise NotFound(detail=f"Mission {mission_id} not found") from exc

    if data.name is not None:
        mission.name = data.name
    if data.status is not None:
        mission.status = data.status
    if data.description is not None:
        mission.description = data.description
    if data.spaceship is not None and data.spaceship != mission.spaceship_id:
        # Reassignable until launch (mirrors Mission.clean(), which the API
        # path bypasses).
        if mission.status != "planned":
            raise HTTPException(
                status_code=400, detail="Cannot reassign a spaceship after launch"
            )
        try:
            ship = await Spaceship.objects.aget(id=data.spaceship)
        except Spaceship.DoesNotExist as exc:
            raise NotFound(detail=f"Spaceship {data.spaceship} not found") from exc
        mission.spaceship = ship

    await mission.asave()
    return await MissionResponse.afrom_model(mission)


@api.delete("/missions/{mission_id}", status_code=204, tags=["missions"])
async def delete_mission(mission_id: int):
    try:
        mission = await Mission.objects.aget(id=mission_id)
    except Mission.DoesNotExist as exc:
        raise NotFound(detail=f"Mission {mission_id} not found") from exc
    await mission.adelete()


@api.get("/missions/{mission_id}/classified", tags=["missions"])
async def get_classified_info(
    mission_id: int,
    clearance: Annotated[str, Header(alias="X-Clearance-Level")],
):
    if clearance not in ["top-secret", "confidential"]:
        raise HTTPException(status_code=403, detail="Insufficient clearance level")

    try:
        mission = await Mission.objects.aget(id=mission_id)
    except Mission.DoesNotExist as exc:
        raise NotFound(detail=f"Mission {mission_id} not found") from exc

    return {
        "mission": mission.name,
        "classified_data": "Launch codes: APOLLO-7749-OMEGA",
    }


@api.get("/missions/{mission_id}/log", tags=["missions"])
async def get_mission_log(mission_id: int):
    try:
        mission = await Mission.objects.aget(id=mission_id)
    except Mission.DoesNotExist as exc:
        raise NotFound(detail=f"Mission {mission_id} not found") from exc

    log = f"=== MISSION LOG: {mission.name} ===\nStatus: {mission.status.upper()}"
    return PlainText(log)


@api.post("/missions/{mission_id}/patch", tags=["missions"])
async def upload_mission_patch(
    mission_id: int,
    patch: Annotated[list[dict], File(alias="patch")],
):
    try:
        mission = await Mission.objects.aget(id=mission_id)
    except Mission.DoesNotExist as exc:
        raise NotFound(detail=f"Mission {mission_id} not found") from exc

    if not patch:
        raise HTTPException(status_code=400, detail="No file uploaded")

    file_info = patch[0]
    filename = file_info.get("filename", "patch.png")
    content = file_info.get("content", b"")

    # Probe D: tenant-isolate uploaded patches. Scope the storage directory by
    # the tenant schema resolved by TenantMainMiddleware so acme and beta
    # uploads never collide, and each tenant only ever sees its own files.
    tenant_schema = getattr(connection, "schema_name", "public")
    media_root = getattr(settings, "TENANT_MEDIA_ROOT", "media/tenant_patches")
    tenant_dir = os.path.join(media_root, tenant_schema, "patches")
    os.makedirs(tenant_dir, exist_ok=True)

    save_path = os.path.join(tenant_dir, f"{mission_id}_{filename}")
    with open(save_path, "wb") as f:
        f.write(content)

    mission.patch_image = save_path
    await mission.asave()

    return {
        "message": "Patch uploaded",
        "filename": filename,
        "tenant_schema": tenant_schema,
        "path": save_path,
    }


@api.post("/missions/{mission_id}/astronauts", tags=["astronauts"])
async def add_astronaut(
    mission_id: int,
    data: Annotated[CreateAstronaut, Form()],
) -> AstronautCreatedResponse:
    try:
        mission = await Mission.objects.aget(id=mission_id)
    except Mission.DoesNotExist as exc:
        raise NotFound(detail=f"Mission {mission_id} not found") from exc

    astronaut = await Astronaut.objects.acreate(
        name=data.name,
        role=data.role,
        mission=mission,
    )
    return await AstronautCreatedResponse.afrom_model(astronaut)


@api.get("/missions/{mission_id}/astronauts", tags=["astronauts"])
async def list_astronauts(mission_id: int) -> AstronautListResponse:
    try:
        mission = await Mission.objects.aget(id=mission_id)
    except Mission.DoesNotExist as exc:
        raise NotFound(detail=f"Mission {mission_id} not found") from exc

    astronaut_tasks = [
        AstronautResponse.afrom_model(astronaut)
        async for astronaut in Astronaut.objects.filter(mission=mission)
    ]
    astronauts = list(await asyncio.gather(*astronaut_tasks))
    return AstronautListResponse(mission=mission.name, astronauts=astronauts)


@api.get("/status-page", tags=["status"])
async def status_page():
    return HTML("<h1>Mission Control: All Systems Operational</h1>")


@api.get("/go", tags=["status"])
async def go_to_dashboard():
    return Redirect("/dashboard")


@api.get("/dashboard", tags=["status"])
async def mission_dashboard(request: Request):
    missions = []
    async for mission in Mission.objects.all()[:20]:
        missions.append(
            {
                "id": mission.id,
                "name": mission.name,
                "status": mission.status,
                "description": mission.description,
            }
        )
    return render(request, "missions/dashboard.html", {"missions": missions})


@api.get("/missions/{mission_id}/detail", tags=["status"])
async def mission_detail(request: Request, mission_id: int):
    try:
        mission = await Mission.objects.aget(id=mission_id)
    except Mission.DoesNotExist as exc:
        raise NotFound(detail=f"Mission {mission_id} not found") from exc

    astronauts = []
    async for astronaut in Astronaut.objects.filter(mission=mission):
        astronauts.append({"name": astronaut.name, "role": astronaut.role})

    context = {
        "mission": {
            "id": mission.id,
            "name": mission.name,
            "status": mission.status,
            "launch_date": mission.launch_date,
            "description": mission.description,
            "patch_image": mission.patch_image,
        },
        "astronauts": astronauts,
    }
    return render(request, "missions/detail.html", context)
