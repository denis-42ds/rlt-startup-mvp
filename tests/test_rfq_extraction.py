import json
from decimal import Decimal
from io import BytesIO
from urllib.error import URLError

import pytest

from rlt_startup.services import rfq_extraction as service


def test_complete_extraction_is_ready(monkeypatch):
    model_data = {
        "product_name": "Стальной лист",
        "quantity": 100,
        "unit": "кг",
        "max_unit_price": 200,
        "currency": "RUB",
        "delivery_destination": "Демонстрационный склад",
        "missing_fields": [],
    }

    def fake_urlopen(request, timeout):
        payload = json.loads(request.data.decode("utf-8"))
        assert payload["model"] == "qwen2.5:3b"
        assert payload["options"]["temperature"] == 0
        assert timeout == service.DEFAULT_TIMEOUT

        body = json.dumps({"response": json.dumps(model_data)}).encode()
        return BytesIO(body)

    monkeypatch.setattr(service, "urlopen", fake_urlopen)

    result = service.extract_rfq("100 кг стального листа, до 200 RUB/кг")

    assert result.ready_to_create_rfq
    assert result.quantity == Decimal("100")
    assert result.max_unit_price == Decimal("200")
    assert result.missing_fields == []


def test_unknown_required_fields_block_rfq_creation():
    result = service.RFQExtraction.from_model_data({
        "product_name": "Стальной лист",
        "quantity": None,
        "unit": None,
        "max_unit_price": None,
        "currency": None,
        "delivery_destination": None,
        "missing_fields": [],
    })

    assert not result.ready_to_create_rfq
    assert {"quantity", "unit"} <= set(result.missing_fields)
    assert "delivery_destination" in result.missing_fields


def test_price_without_currency_is_not_ready():
    result = service.RFQExtraction.from_model_data({
        "product_name": "Цемент",
        "quantity": 300,
        "unit": "кг",
        "max_unit_price": 8000,
        "currency": None,
        "delivery_destination": None,
        "missing_fields": [],
    })

    assert not result.ready_to_create_rfq
    assert "currency" in result.missing_fields


def test_invalid_non_positive_quantity_is_rejected():
    with pytest.raises(service.RFQModelResponseError):
        service.RFQExtraction.from_model_data({
            "product_name": "Стальной лист",
            "quantity": 0,
            "unit": "кг",
            "max_unit_price": None,
            "currency": None,
            "delivery_destination": None,
        })


def test_ollama_unavailable_is_reported(monkeypatch):
    def fake_urlopen(request, timeout):
        raise URLError("connection refused")

    monkeypatch.setattr(service, "urlopen", fake_urlopen)

    with pytest.raises(service.RFQModelUnavailableError):
        service.extract_rfq("Нужен стальной лист")


def test_invalid_model_json_is_rejected(monkeypatch):
    def fake_urlopen(request, timeout):
        body = json.dumps({"response": "not-json"}).encode()
        return BytesIO(body)

    monkeypatch.setattr(service, "urlopen", fake_urlopen)

    with pytest.raises(service.RFQModelResponseError):
        service.extract_rfq("Нужен стальной лист")


def test_empty_request_is_rejected_without_calling_model(monkeypatch):
    def fail_if_called(*args, **kwargs):
        pytest.fail("Ollama не должна вызываться для пустой заявки")

    monkeypatch.setattr(service, "urlopen", fail_if_called)

    with pytest.raises(ValueError):
        service.extract_rfq("   ")
