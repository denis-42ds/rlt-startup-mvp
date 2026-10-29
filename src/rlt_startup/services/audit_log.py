from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

AuditOutcome = Literal["success", "blocked"]


@dataclass(frozen=True, slots=True)
class AuditEvent:
    event_type: str
    order_id: UUID
    occurred_at: datetime
    outcome: AuditOutcome
    reason_code: str | None = None


class InMemoryAuditLog:
    """Append-only журнал событий в памяти для MVP."""

    def __init__(self) -> None:
        self._events: list[AuditEvent] = []

    def append(self, event: AuditEvent) -> None:
        if event.occurred_at.tzinfo is None:
            raise ValueError("occurred_at must include a timezone")
        if event.occurred_at.utcoffset() is None:
            raise ValueError("occurred_at must include a timezone")
        self._events.append(event)

    def list_events(
        self,
        *,
        order_id: UUID | None = None,
    ) -> tuple[AuditEvent, ...]:
        events = self._events
        if order_id is not None:
            events = [
                event
                for event in events
                if event.order_id == order_id
            ]
        return tuple(events)


def make_audit_event(
    *,
    event_type: str,
    order_id: UUID,
    outcome: AuditOutcome,
    reason_code: str | None = None,
    now: datetime | None = None,
) -> AuditEvent:
    occurred_at = now or datetime.now(timezone.utc)
    if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
        raise ValueError("now must include a timezone")

    return AuditEvent(
        event_type=event_type,
        order_id=order_id,
        occurred_at=occurred_at,
        outcome=outcome,
        reason_code=reason_code,
    )
