"""
Tests for budgeting module
"""

import pytest
from datetime import datetime, timedelta
from budgeting import BudgetEngine, AgentSession


@pytest.fixture
def engine():
    """Create a budget engine for testing"""
    return BudgetEngine()


@pytest.fixture
def session():
    """Create a test session"""
    return AgentSession(
        session_id="test-session",
        agent_id="test-agent",
        token_budget=10000,
        cost_budget=1.00,
        timeout_minutes=60
    )


class TestSessionCreation:
    """Tests for session creation and properties"""
    
    def test_session_creation(self, session):
        """Test creating a new session"""
        assert session.session_id == "test-session"
        assert session.agent_id == "test-agent"
        assert session.tokens_used == 0
        assert session.cost_used == 0.0
    
    def test_session_expiration(self, session):
        """Test session expiration calculation"""
        assert not session.is_expired
        
        # Modify creation time to expire the session
        session.created_at = datetime.utcnow() - timedelta(minutes=70)
        assert session.is_expired
    
    def test_token_budget_calculation(self, session):
        """Test token budget remaining calculation"""
        assert session.tokens_remaining == 10000
        
        session.tokens_used = 3000
        assert session.tokens_remaining == 7000
    
    def test_cost_budget_calculation(self, session):
        """Test cost budget remaining calculation"""
        assert session.cost_remaining == 1.00
        
        session.cost_used = 0.25
        assert abs(session.cost_remaining - 0.75) < 0.001


class TestBudgetChecks:
    """Tests for budget checking"""
    
    def test_check_budget_allowed(self, engine, session):
        """Test budget check passes when within limits"""
        result = engine.check_budget(session, estimated_tokens=1000)
        assert result.allowed
        assert result.reason == "Budget check passed"
    
    def test_check_budget_token_exceeded(self, engine, session):
        """Test budget check fails when tokens exceeded"""
        session.tokens_used = 9500
        result = engine.check_budget(session, estimated_tokens=1000)
        assert not result.allowed
        assert "Token budget exceeded" in result.reason
    
    def test_check_budget_cost_exceeded(self, engine, session):
        """Test budget check fails when cost exceeded"""
        tight_session = AgentSession(
            session_id="tight-session",
            agent_id="test-agent",
            token_budget=10000,
            cost_budget=0.0000001,
            timeout_minutes=60,
        )
        result = engine.check_budget(tight_session, estimated_tokens=1000)
        assert not result.allowed
        assert "Cost budget exceeded" in result.reason
    
    def test_check_budget_expired_session(self, engine, session):
        """Test budget check fails for expired session"""
        session.created_at = datetime.utcnow() - timedelta(minutes=70)
        result = engine.check_budget(session, estimated_tokens=100)
        assert not result.allowed
        assert "expired" in result.reason.lower()


class TestUsageRecording:
    """Tests for recording token and cost usage"""
    
    def test_record_token_usage(self, engine, session):
        """Test recording token usage"""
        engine.record_usage(session, tokens=500)
        assert session.tokens_used == 500
    
    def test_record_cost_usage(self, engine, session):
        """Test recording cost usage"""
        engine.record_usage(session, tokens=1000, cost=0.01)
        assert session.cost_used == 0.01
    
    def test_record_multiple_uses(self, engine, session):
        """Test recording multiple operations"""
        engine.record_usage(session, tokens=500, cost=0.005)
        engine.record_usage(session, tokens=500, cost=0.005)
        engine.record_usage(session, tokens=500, cost=0.005)
        
        assert session.tokens_used == 1500
        assert abs(session.cost_used - 0.015) < 0.001
    
    def test_cost_estimation_from_tokens(self, engine, session):
        """Test automatic cost estimation from tokens"""
        engine.record_usage(session, tokens=1000)  # No explicit cost
        assert session.cost_used > 0  # Should have estimated cost


class TestBudgetMetrics:
    """Tests for budget metric calculations"""
    
    def test_utilization_percentage(self, session):
        """Test utilization percentage calculation"""
        assert session.token_utilization_pct == 0.0
        
        session.tokens_used = 5000
        assert session.token_utilization_pct == 50.0
        
        session.tokens_used = 10000
        assert session.token_utilization_pct == 100.0
    
    def test_cost_utilization_percentage(self, session):
        """Test cost utilization percentage"""
        assert session.cost_utilization_pct == 0.0
        
        session.cost_used = 0.50
        assert session.cost_utilization_pct == 50.0


class TestSessionSummary:
    """Tests for session summary reports"""
    
    def test_session_summary(self, engine, session):
        """Test generating session summary"""
        engine.record_usage(session, tokens=1000, cost=0.01)
        summary = engine.get_session_summary(session)
        
        assert summary["session_id"] == "test-session"
        assert summary["agent_id"] == "test-agent"
        assert summary["status"] == "active"
        assert summary["tokens"]["used"] == 1000
        assert float(summary["cost"]["used"].replace("$", "")) == pytest.approx(0.01, abs=0.001)


class TestCostEstimation:
    """Tests for cost estimation"""
    
    def test_estimate_cost_zero_tokens(self, engine):
        """Test cost estimation for zero tokens"""
        cost = engine._estimate_cost(0)
        assert cost == 0.0
    
    def test_estimate_cost_positive_tokens(self, engine):
        """Test cost estimation for positive tokens"""
        cost = engine._estimate_cost(1000)
        assert cost > 0
    
    def test_different_llm_models(self, engine):
        """Test cost estimation for different models"""
        cost_gpt4 = engine._estimate_cost(1000, "gpt-4")
        cost_gpt35 = engine._estimate_cost(1000, "gpt-3.5-turbo")
        
        # GPT-4 should be more expensive
        assert cost_gpt4 > cost_gpt35


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
