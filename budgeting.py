"""
Budget Engine: Token and cost tracking for agent sessions
Prevents runaway agentic loops by enforcing per-session budgets.

Features:
- Per-session token budgets
- Cost tracking and alerts
- Session timeouts
- Budget exhaustion warnings
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


# Pricing estimates for different LLMs (in USD per 1M tokens)
LLM_PRICING = {
    "gpt-4": {"input": 0.03, "output": 0.06},
    "gpt-3.5-turbo": {"input": 0.0005, "output": 0.0015},
    "claude-2": {"input": 0.008, "output": 0.024},
    "claude-instant": {"input": 0.0008, "output": 0.0024},
}


@dataclass
class AgentSession:
    """Tracks token and cost budgets for an agent session"""
    session_id: str
    agent_id: str
    token_budget: int  # Max tokens allowed
    cost_budget: float  # Max cost in USD
    timeout_minutes: int = 60
    
    created_at: datetime = field(default_factory=datetime.utcnow)
    tokens_used: int = 0
    cost_used: float = 0.0
    
    @property
    def expires_at(self) -> datetime:
        """Session expiration time"""
        return self.created_at + timedelta(minutes=self.timeout_minutes)
    
    @property
    def is_expired(self) -> bool:
        """Check if session has expired"""
        return datetime.utcnow() > self.expires_at
    
    @property
    def tokens_remaining(self) -> int:
        """Tokens remaining in budget"""
        return max(0, self.token_budget - self.tokens_used)
    
    @property
    def cost_remaining(self) -> float:
        """Cost remaining in budget"""
        return max(0.0, self.cost_budget - self.cost_used)
    
    @property
    def token_utilization_pct(self) -> float:
        """Percentage of token budget used"""
        if self.token_budget == 0:
            return 0
        return (self.tokens_used / self.token_budget) * 100
    
    @property
    def cost_utilization_pct(self) -> float:
        """Percentage of cost budget used"""
        if self.cost_budget == 0:
            return 0
        return (self.cost_used / self.cost_budget) * 100


@dataclass
class BudgetCheckResult:
    """Result of a budget check"""
    allowed: bool
    reason: str = ""
    tokens_used: int = 0
    tokens_remaining: int = 0
    cost_used: float = 0.0
    cost_remaining: float = 0.0


class BudgetEngine:
    """
    Monitors and enforces token and cost budgets for agent sessions.
    
    Prevents "runaway" agentic loops by stopping execution when:
    - Token budget is exhausted
    - Cost budget is exceeded
    - Session has expired
    """
    
    def __init__(self):
        self.sessions: Dict[str, AgentSession] = {}
        self.cost_estimates = LLM_PRICING  # Configurable LLM pricing
    
    def check_budget(
        self,
        session: AgentSession,
        estimated_tokens: int = 0
    ) -> BudgetCheckResult:
        """
        Check if a session has budget remaining for a tool call.
        
        Args:
            session: Agent session
            estimated_tokens: Estimated tokens for the next operation
        
        Returns:
            BudgetCheckResult with allowed flag
        """
        # Check 1: Session expiration
        if session.is_expired:
            return BudgetCheckResult(
                allowed=False,
                reason=f"Session expired at {session.expires_at.isoformat()}",
                tokens_used=session.tokens_used,
                tokens_remaining=session.tokens_remaining,
                cost_used=session.cost_used,
                cost_remaining=session.cost_remaining
            )
        
        # Check 2: Token budget
        if estimated_tokens > 0:
            if session.tokens_used + estimated_tokens > session.token_budget:
                return BudgetCheckResult(
                    allowed=False,
                    reason=f"Token budget exceeded. Used: {session.tokens_used} / {session.token_budget}. "
                            f"Call would require {estimated_tokens} tokens.",
                    tokens_used=session.tokens_used,
                    tokens_remaining=session.tokens_remaining,
                    cost_used=session.cost_used,
                    cost_remaining=session.cost_remaining
                )
        
        # Check 3: Cost budget
        estimated_cost = self._estimate_cost(estimated_tokens)
        if session.cost_used + estimated_cost > session.cost_budget:
            return BudgetCheckResult(
                allowed=False,
                reason=f"Cost budget exceeded. Used: ${session.cost_used:.4f} / ${session.cost_budget:.4f}. "
                        f"Call would cost ${estimated_cost:.6f}.",
                tokens_used=session.tokens_used,
                tokens_remaining=session.tokens_remaining,
                cost_used=session.cost_used,
                cost_remaining=session.cost_remaining
            )
        
        # Log warnings if approaching limits
        if session.token_utilization_pct > 80:
            logger.warning(
                f"⚠️ Session {session.session_id} at {session.token_utilization_pct:.1f}% "
                f"token budget ({session.tokens_used}/{session.token_budget})"
            )
        
        if session.cost_utilization_pct > 80:
            logger.warning(
                f"⚠️ Session {session.session_id} at {session.cost_utilization_pct:.1f}% "
                f"cost budget (${session.cost_used:.4f}/${session.cost_budget:.4f})"
            )
        
        return BudgetCheckResult(
            allowed=True,
            reason="Budget check passed",
            tokens_used=session.tokens_used,
            tokens_remaining=session.tokens_remaining,
            cost_used=session.cost_used,
            cost_remaining=session.cost_remaining
        )
    
    def record_usage(
        self,
        session: AgentSession,
        tokens: int,
        cost: Optional[float] = None
    ) -> None:
        """
        Record token and cost usage for a session.
        
        Args:
            session: Agent session
            tokens: Tokens used in the operation
            cost: Cost in USD (if not provided, estimated from tokens)
        """
        session.tokens_used += tokens
        
        if cost is None:
            cost = self._estimate_cost(tokens)
        session.cost_used += cost
        
        logger.debug(
            f"Session {session.session_id}: +{tokens} tokens, "
            f"+${cost:.6f} cost. "
            f"Total: {session.tokens_used}/{session.token_budget} tokens, "
            f"${session.cost_used:.4f}/{session.cost_budget:.4f} cost"
        )
    
    def _estimate_cost(self, tokens: int, llm_model: str = "gpt-3.5-turbo") -> float:
        """
        Estimate cost for tokens.
        
        Assumes roughly equal input/output split.
        Default to gpt-3.5-turbo pricing.
        """
        if tokens == 0:
            return 0.0
        
        pricing = self.cost_estimates.get(llm_model, self.cost_estimates["gpt-3.5-turbo"])
        # Assume 50% input, 50% output
        avg_rate = (pricing["input"] + pricing["output"]) / 2
        # Convert from per-million to per-token pricing
        cost_per_token = avg_rate / 1_000_000
        return tokens * cost_per_token
    
    def get_session_summary(self, session: AgentSession) -> Dict[str, Any]:
        """Get a summary of session usage and budget"""
        return {
            "session_id": session.session_id,
            "agent_id": session.agent_id,
            "status": "active" if not session.is_expired else "expired",
            "created_at": session.created_at.isoformat(),
            "expires_at": session.expires_at.isoformat(),
            "time_remaining_minutes": max(0, int(
                (session.expires_at - datetime.utcnow()).total_seconds() / 60
            )),
            "tokens": {
                "used": session.tokens_used,
                "budget": session.token_budget,
                "remaining": session.tokens_remaining,
                "utilization_pct": f"{session.token_utilization_pct:.1f}%"
            },
            "cost": {
                "used": f"${session.cost_used:.4f}",
                "budget": f"${session.cost_budget:.4f}",
                "remaining": f"${session.cost_remaining:.4f}",
                "utilization_pct": f"{session.cost_utilization_pct:.1f}%"
            }
        }
    
    def estimate_tokens_for_operation(self, operation_type: str) -> int:
        """
        Estimate tokens for different operation types.
        
        Useful for pre-checking budget before executing.
        """
        estimates = {
            "search": 300,
            "summarize": 500,
            "analyze": 400,
            "fetch_document": 200,
            "translate": 350,
        }
        return estimates.get(operation_type, 250)


# Example usage
if __name__ == "__main__":
    engine = BudgetEngine()
    
    # Create a session
    session = AgentSession(
        session_id="sess-001",
        agent_id="research-agent",
        token_budget=10000,
        cost_budget=1.00,
        timeout_minutes=60
    )
    
    print("=== Initial Budget ===")
    result = engine.check_budget(session, estimated_tokens=500)
    print(f"Allowed: {result.allowed}")
    print(f"Tokens remaining: {result.tokens_remaining}")
    print(f"Cost remaining: ${result.cost_remaining:.4f}")
    
    # Simulate usage
    print("\\n=== After 1st operation (500 tokens) ===")
    engine.record_usage(session, tokens=500)
    result = engine.check_budget(session, estimated_tokens=500)
    print(f"Allowed: {result.allowed}")
    print(f"Tokens remaining: {result.tokens_remaining}")
    
    # Use more tokens
    print("\\n=== After 2nd operation (9000 tokens) ===")
    engine.record_usage(session, tokens=9000)
    summary = engine.get_session_summary(session)
    print(f"Summary: {summary['tokens']}")
    
    # Check budget (should fail)
    print("\\n=== Budget check for 500 more tokens ===")
    result = engine.check_budget(session, estimated_tokens=500)
    print(f"Allowed: {result.allowed}")
    print(f"Reason: {result.reason}")
