from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from rlt_startup.services.audit_log import (
    AuditEvent,
    InMemoryAuditLog,
    make_audit_event,
)


def test_appends_events_in_order():
    log = InMemoryAuditLog()
    order_id = uuid4()
    now = datetime.now(timezone.utc)

    first = make_audit_event(
        event_type="order_created",
        order_id=order_id,
        outcome="success",
        now=now,
    )
    second = make_audit_event(
        event_type="buyer_confirmed",
        order_id=order_id,
        outcome="success",
        now=now,
    )

    log.append(first)
    log.append(second)

    assert log.list_events() == (first, second)


def test_filters_events_by_order_id():
    log = InMemoryAuditLog()
    first_order = uuid4()
    second_order = uuid4()

    first = make_audit_event(
        event_type="order_created",
        order_id=first_order,
        outcome="success",
    )
    second = make_audit_event(
        event_type="order_created",
        order_id=second_order,
        outcome="success",
    )

    log.append(first)
    log.append(second)

    assert log.list_events(order_id=first_order) == (first,)
    assert log.list_events(order_id=uuid4()) == ()


def test_event_is_immutable():
    event = make_audit_event(
        event_type="order_created",
        order_id=uuid4(),
        outcome="success",
    )

    with pytest.raises(FrozenInstanceError):
        event.event_type = "changed"


def test_rejects_naive_timestamp():
    event = AuditEvent(
        event_type="order_created",
        order_id=uuid4(),
        occurred_at=datetime(2026, 10, 23),
        outcome="success",
    )

    with pytest.raises(ValueError, match="timezone"):
        InMemoryAuditLog().append(event)


def test_factory_rejects_naive_timestamp():
    with pytest.raises(ValueError, match="timezone"):
        make_audit_event(
            event_type="order_created",
            order_id=uuid4(),
            outcome="success",
            now=datetime(2026, 10, 23),
        )
