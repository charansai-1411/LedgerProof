"""Tamper-evident, append-only audit — enforced in code, not just claimed (critique 17).

Every event is chained: `event_hash = sha256(previous_event_hash + canonical(event))`. Altering or
dropping any past event breaks every hash after it, so `AuditChain.verify()` detects tampering. No
blockchain, no external service — just a hash chain, which is the right amount of machinery for a
tamper-evident finance log.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

GENESIS = "0" * 64


def _canonical(obj: dict) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


@dataclass
class AuditEvent:
    audit_event_id: int
    timestamp: str
    actor: str          # engine | agent | verifier | governor | human | system
    event: dict
    previous_event_hash: str
    event_hash: str


@dataclass
class AuditChain:
    """Append-only in behaviour: there is no update or delete, only append + verify."""

    events: list[AuditEvent] = field(default_factory=list)

    def _tip(self) -> str:
        return self.events[-1].event_hash if self.events else GENESIS

    def append(self, actor: str, event: dict, timestamp: str) -> AuditEvent:
        prev = self._tip()
        eid = len(self.events)
        body = _canonical({"id": eid, "ts": timestamp, "actor": actor, "event": event, "prev": prev})
        h = hashlib.sha256(body.encode("utf-8")).hexdigest()
        ev = AuditEvent(eid, timestamp, actor, event, prev, h)
        self.events.append(ev)
        return ev

    def verify(self) -> dict:
        """Re-derive every hash from genesis; report the first break if any."""
        prev = GENESIS
        for e in self.events:
            body = _canonical({"id": e.audit_event_id, "ts": e.timestamp, "actor": e.actor,
                               "event": e.event, "prev": prev})
            h = hashlib.sha256(body.encode("utf-8")).hexdigest()
            if h != e.event_hash or e.previous_event_hash != prev:
                return {"intact": False, "broken_at": e.audit_event_id, "length": len(self.events)}
            prev = e.event_hash
        return {"intact": True, "broken_at": None, "length": len(self.events), "tip": prev}

    def to_list(self) -> list[dict]:
        return [{"audit_event_id": e.audit_event_id, "timestamp": e.timestamp, "actor": e.actor,
                 "event": e.event, "previous_event_hash": e.previous_event_hash[:12],
                 "event_hash": e.event_hash[:12]} for e in self.events]
