from fastapi.testclient import TestClient
from rlt_startup.api import app
from uuid import uuid4

client = TestClient(app)


def test_health_check_returns_ok() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_openapi_schema_is_available() -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["title"] == "RLT.Startup API"

def test_create_rfq_returns_created_rfq() -> None:
    response = client.post(
        "/rfqs",
        json={
            "buyer_organization_id": "11111111-1111-4111-8111-111111111111",
            "items": [
                {
                    "product_name": "Стальной лист",
                    "quantity": "100",
                    "unit": "кг",
                }
            ],
        },
    )

    assert response.status_code == 201

    data = response.json()
    assert data["buyer_organization_id"] == "11111111-1111-4111-8111-111111111111"
    assert len(data["items"]) == 1
    assert data["items"][0]["product_name"] == "Стальной лист"
    assert data["status"] == "draft"
    assert data["id"]
    assert data["created_at"]


def test_create_rfq_rejects_invalid_data() -> None:
    response = client.post(
        "/rfqs",
        json={
            "buyer_organization_id": "not-a-uuid",
            "items": [],
        },
    )

    assert response.status_code == 422

def test_get_rfq_returns_previously_created_rfq() -> None:
    create_response = client.post(
        "/rfqs",
        json={
            "buyer_organization_id": "11111111-1111-4111-8111-111111111111",
            "items": [
                {
                    "product_name": "Стальной лист",
                    "quantity": "100",
                    "unit": "кг",
                }
            ],
        },
    )
    assert create_response.status_code == 201

    rfq_id = create_response.json()["id"]
    response = client.get(f"/rfqs/{rfq_id}")

    assert response.status_code == 200
    assert response.json()["id"] == rfq_id
    assert response.json()["items"][0]["product_name"] == "Стальной лист"


def test_get_unknown_rfq_returns_404() -> None:
    response = client.get(f"/rfqs/{uuid4()}")

    assert response.status_code == 404
