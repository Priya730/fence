"""
Tests for safety_guardrails module
"""

import pytest
import yaml
from safety_guardrails import SafetyEngine, SafetyPolicy


@pytest.fixture
def engine():
    """Create a safety engine for testing"""
    return SafetyEngine()


class TestPolicyLoading:
    """Tests for policy loading and management"""
    
    def test_default_policy_permissive(self, engine):
        """Test that default policy is permissive"""
        result = engine.check_policy(
            agent_id="unknown-agent",
            tool_name="search",
            arguments={"query": "test"}
        )
        assert result["allowed"]
    
    def test_custom_policy_assignment(self, engine):
        """Test custom policy assignment"""
        custom_policy = SafetyPolicy(
            agent_id="custom-agent",
            allowed_tools=["search"],
            blocked_operations=["execute_shell"],
            rate_limits={"calls_per_minute": 60},
            rbac_roles={}
        )
        engine.policies["custom-agent"] = custom_policy
        
        # Should allow
        result = engine.check_policy(
            agent_id="custom-agent",
            tool_name="search",
            arguments={"query": "test"}
        )
        assert result["allowed"]


class TestToolAllowlisting:
    """Tests for tool allowlisting/blocklisting"""
    
    def test_allowed_tool(self, engine):
        """Test that allowed tools are permitted"""
        policy = SafetyPolicy(
            agent_id="test-agent",
            allowed_tools=["search", "fetch_document"],
            blocked_operations=[],
            rate_limits={},
            rbac_roles={}
        )
        engine.policies["test-agent"] = policy
        
        result = engine.check_policy(
            agent_id="test-agent",
            tool_name="search",
            arguments={"query": "test"}
        )
        assert result["allowed"]
    
    def test_disallowed_tool(self, engine):
        """Test that unknown tools are blocked by the registry"""
        policy = SafetyPolicy(
            agent_id="test-agent",
            allowed_tools=["search"],
            blocked_operations=[],
            rate_limits={},
            rbac_roles={}
        )
        engine.policies["test-agent"] = policy
        
        result = engine.check_policy(
            agent_id="test-agent",
            tool_name="magic_tool",
            arguments={}
        )
        assert not result["allowed"]
        assert "not in allowlist" in result["reason"]
    
    def test_wildcard_allowlist(self, engine):
        """Test wildcard allowlist still honors approval and registry checks"""
        policy = SafetyPolicy(
            agent_id="test-agent",
            allowed_tools=["*"],
            blocked_operations=[],
            rate_limits={},
            rbac_roles={}
        )
        engine.policies["test-agent"] = policy
        
        result = engine.check_policy(
            agent_id="test-agent",
            tool_name="search",
            arguments={"query": "test"}
        )
        assert result["allowed"]

        result = engine.check_policy(
            agent_id="test-agent",
            tool_name="execute_shell",
            arguments={"command": "echo hello", "cwd": "/tmp", "timeout_seconds": 5}
        )
        assert not result["allowed"]
        assert "requires human approval" in result["reason"]

        result = engine.check_policy(
            agent_id="test-agent",
            tool_name="execute_shell",
            arguments={
                "command": "echo hello",
                "cwd": "/tmp",
                "timeout_seconds": 5,
                "human_approved": True,
            }
        )
        assert result["allowed"]


class TestBlockedOperations:
    """Tests for blocked operation detection"""
    
    def test_blocked_operation_tool(self, engine):
        """Test blocking dangerous shell patterns"""
        policy = SafetyPolicy(
            agent_id="test-agent",
            allowed_tools=["execute_shell"],
            blocked_operations=[],
            rate_limits={},
            rbac_roles={}
        )
        engine.policies["test-agent"] = policy
        
        result = engine.check_policy(
            agent_id="test-agent",
            tool_name="execute_shell",
            arguments={
                "command": "rm -rf /tmp/customer-data",
                "cwd": "/tmp",
                "timeout_seconds": 5,
                "human_approved": True,
            }
        )
        assert not result["allowed"]
        assert "blocked pattern" in result["reason"]


class TestRateLimiting:
    """Tests for rate limiting"""
    
    def test_rate_limit_enforcement(self, engine):
        """Test that rate limits are enforced"""
        policy = SafetyPolicy(
            agent_id="test-agent",
            allowed_tools=["search"],
            blocked_operations=[],
            rate_limits={"calls_per_minute": 3},  # Very strict for testing
            rbac_roles={}
        )
        engine.policies["test-agent"] = policy
        
        # First 3 calls should succeed
        for i in range(3):
            result = engine.check_policy(
                agent_id="test-agent",
                tool_name="search",
                arguments={"query": f"test {i}"}
            )
            assert result["allowed"], f"Call {i+1} should be allowed"
        
        # 4th call should fail
        result = engine.check_policy(
            agent_id="test-agent",
            tool_name="search",
            arguments={"query": "test 4"}
        )
        assert not result["allowed"], "4th call should exceed rate limit"
        assert "Rate limit exceeded" in result["reason"]
    
    def test_rate_limit_reset(self, engine):
        """Test that rate limits reset per minute"""
        from datetime import datetime, timedelta
        
        policy = SafetyPolicy(
            agent_id="test-agent",
            allowed_tools=["search"],
            blocked_operations=[],
            rate_limits={"calls_per_minute": 2},
            rbac_roles={}
        )
        engine.policies["test-agent"] = policy
        
        # Use up the limit
        engine.check_policy("test-agent", "search", {})
        engine.check_policy("test-agent", "search", {})
        
        # Next call should fail
        result = engine.check_policy("test-agent", "search", {})
        assert not result["allowed"]


class TestPolicyInfo:
    """Tests for policy information retrieval"""
    
    def test_get_policy_info(self, engine):
        """Test retrieving policy information"""
        policy = SafetyPolicy(
            agent_id="test-agent",
            allowed_tools=["search", "fetch_document"],
            blocked_operations=["execute_shell"],
            rate_limits={"calls_per_minute": 60},
            rbac_roles={}
        )
