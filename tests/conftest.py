"""Shared pytest fixtures for Fence tests."""

from datetime import datetime, timedelta

import pytest

from adapters import ToolCallAdapter
from budgeting import AgentSession, BudgetEngine
from safety_guardrails import SafetyEngine
from semantic_validator import SemanticValidator
from storage import FenceStore


@pytest.fixture
def validator():
    return SemanticValidator()


@pytest.fixture
def safety_engine():
    return SafetyEngine()


@pytest.fixture
def budget_engine():
    return BudgetEngine()


@pytest.fixture
def session():
    return AgentSession(
        session_id="test-session",
        agent_id="test-agent",
        token_budget=10000,
        cost_budget=1.0,
        timeout_minutes=60,
    )


@pytest.fixture
def store(tmp_path):
    return FenceStore(db_path=str(tmp_path / "fence.db"))


@pytest.fixture
def adapter():
    return ToolCallAdapter()


@pytest.fixture
def active_session():
    created_at = datetime.utcnow()
    return {
        "created_at": created_at,
        "expires_at": created_at + timedelta(minutes=60),
    }

