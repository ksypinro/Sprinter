import logging
from typing import Optional

from orchestrator.models import EventStatus, OrchestratorEvent
from orchestrator.store import OrchestratorStore

logger = logging.getLogger(__name__)

class EventBuffer:
    """Manages the incoming event queue."""

    def __init__(self, store: OrchestratorStore):
        self.store = store

    def submit(self, event: OrchestratorEvent) -> str:
        """Add an event to the pending queue."""

        self.store.save_event(event, EventStatus.PENDING)
        logger.debug("Buffered event: %s (%s)", event.event_id, event.event_type)
        return event.event_id

    def poll(self) -> Optional[OrchestratorEvent]:
        """Claim the next pending event."""

        return self.store.claim_next_event()
