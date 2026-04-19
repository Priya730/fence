"""Tests for SQLite-backed Fence storage."""

from datetime import datetime, timedelta
from pathlib import Path

from storage import FenceStore


def test_session_round_trip(tmp_path):
    db_path = tmp_path / "fence.db"
    store = FenceStore(db_path=str(db_path))

    created_at = datetime.utcnow()
    expires_at = created_at + timedelta(minutes=60)

    store.upsert_session(
        session_id="session-1",
        agent_id="research-agent",
        created_at=created_at,
        expires_at=expires_at,
        timeout_minutes=60,
        token_budget=1000,
        cost_budget=1.0,
        tokens_used=125,
        cost_used=0.01,
        metadata={"source": "test"},
    )

    row = store.get_session("session-1")
    assert row is not None
    assert row["agent_id"] == "research-agent"
    assert row["tokens_used"] == 125
    assert row["timeout_minutes"] == 60


def test_audit_event_round_trip(tmp_path):
    db_path = tmp_path / "fence.db"
    store = FenceStore(db_path=str(db_path))

    store.record_audit_event(
        event_id="event-1",
        session_id="session-1",
        agent_id="research-agent",
        tool_name="search",
        decision="allowed",
        reason="ok",
        metadata={"provider": "generic"},
    )

    events = store.list_audit_events(session_id="session-1")
    assert len(events) == 1
    assert events[0]["tool_name"] == "search"
    assert "provider" in events[0]["metadata"]
