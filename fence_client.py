"""
Small Python client for integrating Fence into other projects.

This keeps the integration surface simple:
- call one method before executing a tool
- inspect the decision
- execute the tool only if Fence allowed it
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx


@dataclass
class FenceDecision:
    """A normalized decision returned by Fence."""

    success: bool
    decision: str
    trace_id: str
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class FenceClient:
    """Tiny HTTP client for calling Fence from an agent loop."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000",
        api_key: Optional[str] = None,
        timeout: float = 30.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def health(self) -> Dict[str, Any]:
        """Check whether Fence is alive."""
        response = httpx.get(f"{self.base_url}/health", timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def decide_tool_call(
        self,
        agent_id: str,
        tool_name: str,
        arguments: Dict[str, Any],
        *,
        provider: str = "generic",
        session_id: Optional[str] = None,
        token_budget: Optional[int] = None,
        cost_budget: Optional[float] = None,
        timeout_minutes: Optional[int] = None,
    ) -> FenceDecision:
        """
        Ask Fence whether a tool call should proceed.

        This is the main integration point for agent loops.
        """
        payload: Dict[str, Any] = {
            "agent_id": agent_id,
            "tool_name": tool_name,
            "arguments": arguments,
            "provider": provider,
        }
        if session_id is not None:
            payload["session_id"] = session_id
        if token_budget is not None:
            payload["token_budget"] = token_budget
        if cost_budget is not None:
            payload["cost_budget"] = cost_budget
        if timeout_minutes is not None:
            payload["timeout_minutes"] = timeout_minutes

        headers = {}
        if self.api_key:
            headers["X-API-Key"] = self.api_key

        response = httpx.post(
            f"{self.base_url}/call",
            headers=headers,
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        return FenceDecision(
            success=data["success"],
            decision=data["decision"],
            trace_id=data["trace_id"],
            result=data.get("result"),
            error=data.get("error"),
            metadata=data.get("metadata"),
        )

    def decide_provider_payload(
        self,
        provider: str,
        payload: Dict[str, Any],
    ) -> FenceDecision:
        """
        Ask Fence to normalize a provider-shaped payload first.
        """
        headers = {}
        if self.api_key:
            headers["X-API-Key"] = self.api_key

        response = httpx.post(
            f"{self.base_url}/v1/decide",
            headers=headers,
            json={"provider": provider, "payload": payload},
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        return FenceDecision(
            success=data["success"],
            decision=data["decision"],
            trace_id=data["trace_id"],
            result=data.get("result"),
            error=data.get("error"),
            metadata=data.get("metadata"),
        )

    def can_execute(
        self,
        agent_id: str,
        tool_name: str,
        arguments: Dict[str, Any],
        **kwargs: Any,
    ) -> bool:
        """Convenience wrapper for boolean checks."""
        return self.decide_tool_call(agent_id, tool_name, arguments, **kwargs).success
