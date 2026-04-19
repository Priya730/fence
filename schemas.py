"""
Schemas and data models for the MCP middleware proxy.
"""

from dataclasses import dataclass
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field


# ============================================================================
# Request/Response Models
# ============================================================================

@dataclass
class ToolCall:
    """A tool call made by an LLM agent"""
    agent_id: str
    tool_name: str
    arguments: Dict[str, Any]
    session_id: Optional[str] = None


@dataclass
class ValidationResult:
    """Result of schema validation"""
    is_valid: bool
    errors: Optional[List[str]] = None
    corrective_guidance: Optional[str] = None
    validated_data: Optional[Dict[str, Any]] = None


@dataclass
class SafetyCheckResult:
    """Result of safety policy check"""
    allowed: bool
    reason: str
    policy_id: Optional[str] = None


@dataclass
class BudgetCheckResult:
    """Result of budget check"""
    allowed: bool
    reason: str = ""
    tokens_used: int = 0
    tokens_remaining: int = 0
    cost_used: float = 0.0
    cost_remaining: float = 0.0


# ============================================================================
# Observability Models
# ============================================================================

class TraceSpanAttributes(BaseModel):
    """Attributes for a trace span"""
    trace_id: str
    span_id: str
    parent_span_id: Optional[str] = None
    operation: str
    start_time: str
    duration_ms: float
    status: str  # "success", "error", "unknown"
    attributes: Dict[str, Any] = Field(default_factory=dict)


class TraceEvent(BaseModel):
    """Event within a span"""
    name: str
    timestamp: str
    attributes: Dict[str, Any] = Field(default_factory=dict)


# ============================================================================
# Configuration Models
# ============================================================================

class SafetyPolicyConfig(BaseModel):
    """Safety policy configuration"""
    agent_id: str
    allowed_tools: List[str]
    blocked_operations: List[str]
    rate_limits: Dict[str, int]
    rbac: Dict[str, List[str]] = Field(default_factory=dict)


class SessionConfig(BaseModel):
    """Session configuration"""
    token_budget: int
    cost_budget: float
    timeout_minutes: int = 60


# ============================================================================
# Metrics Models
# ============================================================================

class TokenMetric(BaseModel):
    """Token usage metric"""
    agent_id: str
    tokens: int
    timestamp: str
    operation: str


class CostMetric(BaseModel):
    """Cost metric"""
    agent_id: str
    cost_usd: float
    tokens: int
    llm_model: str
    timestamp: str


# ============================================================================
# Report Models
# ============================================================================

class SessionReport(BaseModel):
    """Session usage report"""
    session_id: str
    agent_id: str
    created_at: str
    ended_at: Optional[str] = None
    total_calls: int
    failed_calls: int
    tokens_used: int
    cost_usd: float
    safety_violations: int
    validation_failures: int
