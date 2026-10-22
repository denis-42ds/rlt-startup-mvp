import json
import pytest
from uuid import uuid4
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
    original_credentials = app.state.demo_credentials

    buyer_org_id = uuid4()
    supplier_org_id = uuid4()
    other_buyer_org_id = uuid4()

    buyer_token = "test-buyer-token"
    supplier_token = "test-supplier-token"
    other_buyer_token = "test-other-buyer-token"
    orchestrator_token = "test-orchestrator-token"

    from rlt_startup.services.authentication import load_demo_credentials

    app.state.demo_credentials = load_demo_credentials(
        json.dumps(
            [
                {
                    "token": buyer_token,
                    "subject_id": str(uuid4()),
                    "organization_id": str(buyer_org_id),
                    "role": "buyer",
                },
                {
                    "token": supplier_token,
                    "subject_id": str(uuid4()),
                    "organization_id": str(supplier_org_id),
                    "role": "supplier",
                },
                {
                    "token": other_buyer_token,
                    "subject_id": str(uuid4()),
                    "organization_id": str(other_buyer_org_id),
                    "role": "buyer",
                },
                {
                    "token": orchestrator_token,
                    "subject_id": str(uuid4()),
                    "organization_id": str(uuid4()),
                    "role": "orchestrator",
                },
            ]
        )
    )

    app.state.test_buyer_org_id = buyer_org_id
    app.state.test_supplier_org_id = supplier_org_id
    app.state.test_other_buyer_org_id = other_buyer_org_id
    app.state.test_buyer_token = buyer_token
    app.state.test_supplier_token = supplier_token
    app.state.test_other_buyer_token = other_buyer_token
    app.state.test_orchestrator_token = orchestrator_token

    app.state.rfq_repository = InMemoryRFQRepository()
    app.state.offer_repository = InMemoryOfferRepository()
    app.state.order_repository = InMemoryOrderRepository()
    app.state.supplier_adapters = {}

    try:
        with TestClient(app, headers={"Authorization": "Bearer test-buyer-token"},) as test_client:
            yield test_client
    finally:
        app.state.rfq_repository = original_rfq_repository
        app.state.offer_repository = original_offer_repository
        app.state.order_repository = original_order_repository
        app.state.supplier_adapters = original_adapters
        app.state.demo_credentials = original_credentials

        for name in (
            "test_buyer_org_id",
            "test_supplier_org_id",
            "test_buyer_token",
            "test_supplier_token",
            "test_other_buyer_token",
            "test_other_buyer_org_id",
            "test_orchestrator_token",
        ):
            if hasattr(app.state, name):
                delattr(app.state, name)
