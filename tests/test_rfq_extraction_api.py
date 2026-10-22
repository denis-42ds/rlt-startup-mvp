from decimal import Decimal

from rlt_startup import api
from rlt_startup.services.rfq_extraction import (
    RFQExtraction,
    RFQModelResponseError,
    RFQModelUnavailableError,
)


def test_extract_rfq_returns_validated_fields(client, monkeypatch):
    expected = RFQExtraction.from_model_data(
        {
            "product_name": "Стальной лист",
            "quantity": "100",
            "unit": "кг",
            "max_unit_price": "200",
            "currency": "RUB",
            "delivery_destination": None,
        }
    )

    received = {}

    def fake_extract_rfq(text: str) -> RFQExtraction:
        received["text"] = text
        return expected

    monkeypatch.setattr(api, "extract_rfq", fake_extract_rfq)

    response = client.post(
        "/rfqs/extract",
        json={"text": "Нужно 100 кг стального листа, до 200 RUB за кг"},
    )

    assert response.status_code == 200
    assert received["text"] == "Нужно 100 кг стального листа, до 200 RUB за кг"

    data = response.json()
    assert data["product_name"] == "Стальной лист"
    assert Decimal(data["quantity"]) == Decimal("100")
    assert data["unit"] == "кг"
    assert Decimal(data["max_unit_price"]) == Decimal("200")
    assert data["currency"] == "RUB"
    assert data["ready_to_create_rfq"] is True


def test_extract_rfq_rejects_empty_text(client, monkeypatch):
    def should_not_run(text: str):
        raise AssertionError("Model must not be called")

    monkeypatch.setattr(api, "extract_rfq", should_not_run)

    response = client.post("/rfqs/extract", json={"text": "   "})

    assert response.status_code == 422


def test_extract_rfq_returns_503_when_model_unavailable(
    client, monkeypatch
):
    def unavailable(text: str):
        raise RFQModelUnavailableError("Ollama unavailable")

    monkeypatch.setattr(api, "extract_rfq", unavailable)

    response = client.post(
        "/rfqs/extract",
        json={"text": "100 кг стального листа"},
    )

    assert response.status_code == 503


def test_extract_rfq_returns_502_for_invalid_model_response(
    client, monkeypatch
):
    def invalid_response(text: str):
        raise RFQModelResponseError("Invalid response")

    monkeypatch.setattr(api, "extract_rfq", invalid_response)

    response = client.post(
        "/rfqs/extract",
        json={"text": "100 кг стального листа"},
    )

    assert response.status_code == 502


def test_extract_rfq_requires_authentication(client, monkeypatch):
    def should_not_run(text: str):
        raise AssertionError("Model must not be called")

    monkeypatch.setattr(api, "extract_rfq", should_not_run)

    response = client.post(
        "/rfqs/extract",
        headers={"Authorization": ""},
        json={"text": "100 кг стального листа"},
    )

    assert response.status_code == 401


def test_extract_rfq_rejects_supplier_role(client, monkeypatch):
    def should_not_run(text: str):
        raise AssertionError("Model must not be called")

    monkeypatch.setattr(api, "extract_rfq", should_not_run)

    response = client.post(
        "/rfqs/extract",
        headers={
            "Authorization": (
                f"Bearer {client.app.state.test_supplier_token}"
            )
        },
        json={"text": "100 кг стального листа"},
    )

    assert response.status_code == 403
