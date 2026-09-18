import pytest


@pytest.mark.django_db
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


@pytest.mark.django_db
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


@pytest.mark.django_db
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


@pytest.mark.django_db
def test_mission_detail_page(client):
    create_response = client.post("/missions", json={"name": "Endeavour"})
    mission_id = create_response.json()["id"]

    response = client.get(f"/missions/{mission_id}/detail")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Endeavour" in response.text
    assert "No astronauts assigned yet." in response.text


@pytest.mark.django_db
def test_mission_detail_page_not_found(client):
    response = client.get("/missions/999/detail")
    assert response.status_code == 404


@pytest.mark.django_db
def test_missions_are_isolated_per_tenant(client, beta_client):
    """Missions created under the acme tenant must not be visible from beta."""
    client.post("/missions", json={"name": "Acme Secret"})

    acme_list = client.get("/missions")
    assert acme_list.status_code == 200
    assert any(m["name"] == "Acme Secret" for m in acme_list.json()["missions"])

    beta_list = beta_client.get("/missions")
    assert beta_list.status_code == 200
    assert beta_list.json()["count"] == 0
    assert all(m["name"] != "Acme Secret" for m in beta_list.json()["missions"])
