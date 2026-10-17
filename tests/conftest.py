import pytest
from fastapi.testclient import TestClient

from rlt_startup.api import app
from rlt_startup.repositories.rfq_repository import InMemoryRFQRepository
from rlt_startup.repositories.offer_repository import InMemoryOfferRepository
from rlt_startup.repositories.order_repository import InMemoryOrderRepository

@pytest.fixture
def client():
    original_rfq_repository = app.state.rfq_repository
    original_offer_repository = app.state.offer_repository
    original_order_repository = app.state.order_repository
    original_adapters = app.state.supplier_adapters

    app.state.rfq_repository = InMemoryRFQRepository()
    app.state.offer_repository = InMemoryOfferRepository()
    app.state.order_repository = InMemoryOrderRepository()
    app.state.supplier_adapters = {}

    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.state.rfq_repository = original_rfq_repository
        app.state.offer_repository = original_offer_repository
        app.state.order_repository = original_order_repository
        app.state.supplier_adapters = original_adapters
