from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseORMModelWithId, utcnow


class AweProcessedEvent(BaseORMModelWithId):
    """Idempotency ledger for inbound AWE webhooks.

    AWE retries a delivery until it gets a 2xx, so the same ``X-Approval-Event-Id``
    may arrive more than once. We insert the event id here on first processing;
    a duplicate is detected by primary-key presence and ACKed without re-applying
    the state change.
    """

    __tablename__ = "cm_awe_processed_events"

    # We store the AWE event id directly as the primary key.
    event_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    event_type: Mapped[str] = mapped_column(String(64))
    request_id: Mapped[str] = mapped_column(String(64), index=True)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
