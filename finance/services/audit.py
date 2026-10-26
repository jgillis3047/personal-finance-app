"""Audit trail for important financial edits."""
from __future__ import annotations

import json
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from finance.db.models import AuditLog


def _jsonable(v):
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return v


def record(session: Session, entity: str, entity_id: int | None, action: str, changes: dict | None = None) -> None:
    payload = None
    if changes:
        payload = json.dumps({k: [_jsonable(a) for a in v] if isinstance(v, tuple) else _jsonable(v)
                              for k, v in changes.items()})
    session.add(AuditLog(entity=entity, entity_id=entity_id, action=action, changes=payload))


def diff(obj, updates: dict) -> dict:
    """Return {field: (old, new)} for fields that actually change."""
    out = {}
    for k, new in updates.items():
        old = getattr(obj, k)
        if old != new:
            out[k] = (old, new)
    return out


def recent(session: Session, limit: int = 200) -> list[AuditLog]:
    return list(session.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)))
