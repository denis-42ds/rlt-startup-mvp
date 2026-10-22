import json
import secrets
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from fastapi import HTTPException, status


class UserRole(StrEnum):
    BUYER = "buyer"
    SUPPLIER = "supplier"
    ORCHESTRATOR = "orchestrator"


@dataclass(frozen=True)
class Identity:
    subject_id: UUID
    organization_id: UUID
    role: UserRole


@dataclass(frozen=True)
class DemoCredential:
    token: str
    identity: Identity


def load_demo_credentials(raw: str | None) -> tuple[DemoCredential, ...]:
    """Загрузить демо-учётные данные из JSON-конфигурации."""
    if not raw:
        return ()

    try:
        entries = json.loads(raw)
        if not isinstance(entries, list):
            raise ValueError("Expected a JSON array")

        credentials = []
        seen_tokens: set[str] = set()

        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError("Each credential must be an object")

            token = entry["token"]
            if not isinstance(token, str) or not token:
                raise ValueError("Token must be a non-empty string")

            if token in seen_tokens:
                raise ValueError("Duplicate demo token")
            seen_tokens.add(token)

            identity = Identity(
                subject_id=UUID(entry["subject_id"]),
                organization_id=UUID(entry["organization_id"]),
                role=UserRole(entry["role"]),
            )
            credentials.append(
                DemoCredential(token=token, identity=identity)
            )

        return tuple(credentials)

    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Invalid demo authentication configuration") from exc


def authenticate_token(
    authorization: str | None,
    credentials: tuple[DemoCredential, ...],
) -> Identity:
    """Проверить Bearer-токен и вернуть серверную идентичность."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    supplied_token = authorization.removeprefix("Bearer ")

    if not supplied_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    matched_identity = None

    # Проверяем все настроенные токены, не завершая цикл при совпадении.
    for credential in credentials:
        if secrets.compare_digest(supplied_token, credential.token):
            matched_identity = credential.identity

    if matched_identity is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return matched_identity
