import pytest
from django_bolt.testing import TestClient

from missions.api import api


@pytest.fixture
def client():
    with TestClient(api) as client:
        yield client


def test_mission_control_status(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["status"] == "operational"


@pytest.mark.django_db
def test_create_and_get_mission(client):
    create_response = client.post(
        "/missions",
        json={
            "name": "Apollo 13",
            "description": "Lunar mission",
            "launch_date": "2026-09-18T10:00:00Z",
        },
    )
    assert create_response.status_code == 200
    assert create_response.json()["message"] == "Mission created successfully"

    mission_id = create_response.json()["id"]
    get_response = client.get(f"/missions/{mission_id}")
    assert get_response.status_code == 200
    assert get_response.json()["name"] == "Apollo 13"


@pytest.mark.django_db
def test_create_mission_rejects_test_name(client):
    response = client.post("/missions", json={"name": "test mission"})
    assert response.status_code == 422


def test_nonexistent_route_404(client):
    assert client.get("/nonexistent").status_code == 404


@pytest.mark.django_db
def test_get_nonexistent_mission_404(client):
    response = client.get("/missions/999")
    assert response.status_code == 404


@pytest.mark.django_db
def test_classified_info_requires_clearance(client):
    create_response = client.post("/missions", json={"name": "Voyager"})
    mission_id = create_response.json()["id"]

    missing = client.get(f"/missions/{mission_id}/classified")
    assert missing.status_code == 422

    denied = client.get(
        f"/missions/{mission_id}/classified",
        headers={"X-Clearance-Level": "public"},
    )
    assert denied.status_code == 403

    allowed = client.get(
        f"/missions/{mission_id}/classified",
        headers={"X-Clearance-Level": "top-secret"},
    )
    assert allowed.status_code == 200
    assert "classified_data" in allowed.json()


@pytest.mark.django_db
def test_mission_log_plain_text(client):
    create_response = client.post("/missions", json={"name": "Gemini"})
    mission_id = create_response.json()["id"]

    response = client.get(f"/missions/{mission_id}/log")
    assert response.status_code == 200
    assert "MISSION LOG: Gemini" in response.text
    assert "STATUS: PLANNED" in response.text.upper()


@pytest.mark.django_db
def test_add_astronaut_to_mission(client):
    create_response = client.post("/missions", json={"name": "Artemis"})
    mission_id = create_response.json()["id"]

    response = client.post(
        f"/missions/{mission_id}/astronauts",
        data={"name": "Alice", "role": "Commander"},
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Alice"

    list_response = client.get(f"/missions/{mission_id}/astronauts")
    assert list_response.status_code == 200
    assert len(list_response.json()["astronauts"]) == 1


def test_go_redirect(client):
    response = client.get("/go", follow_redirects=False)
    assert response.status_code == 307 or response.status_code == 302
    assert response.headers.get("location") == "/dashboard"


@pytest.mark.django_db
def test_dashboard_page(client):
    client.post("/missions", json={"name": "Discovery"})
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Discovery" in response.text
