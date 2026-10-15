import pytest
from fastapi.testclient import TestClient

from rlt_startup.api import app, get_rfq_repository
from rlt_startup.repositories.rfq_repository import InMemoryRFQRepository


@pytest.fixture
def client():
    repository = InMemoryRFQRepository()
    app.dependency_overrides[get_rfq_repository] = lambda: repository

    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_rfq_repository, None)
