import json
from uuid import uuid4

import pytest
from fastapi import HTTPException

from rlt_startup.services.authentication import (
    Identity,
    UserRole,
    authenticate_token,
    load_demo_credentials,
)


def make_config(token: str = "test-secret-token") -> str:
    return json.dumps(
        [
            {
                "token": token,
                "subject_id": str(uuid4()),
                "organization_id": str(uuid4()),
                "role": "buyer",
            }
        ]
    )


def test_load_demo_credentials():
    credentials = load_demo_credentials(make_config())

    assert len(credentials) == 1
    assert credentials[0].identity.role == UserRole.BUYER


def test_authenticate_valid_token():
    credentials = load_demo_credentials(make_config())
    identity = authenticate_token("Bearer test-secret-token", credentials)

    assert isinstance(identity, Identity)
    assert identity.role == UserRole.BUYER


@pytest.mark.parametrize(
    "authorization",
    [
        None,
        "",
        "Basic test-secret-token",
        "Bearer ",
        "Bearer wrong-token",
    ],
)
def test_authenticate_rejects_missing_or_invalid_token(authorization):
    credentials = load_demo_credentials(make_config())

    with pytest.raises(HTTPException) as exc_info:
        authenticate_token(authorization, credentials)

    assert exc_info.value.status_code == 401


def test_empty_configuration_rejects_all_tokens():
    with pytest.raises(HTTPException) as exc_info:
        authenticate_token("Bearer test-secret-token", ())

    assert exc_info.value.status_code == 401


def test_invalid_configuration_is_rejected():
    with pytest.raises(ValueError):
        load_demo_credentials('{"token": "not-an-array"}')
