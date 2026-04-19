"""
Normalization adapters for different agent/tool payload shapes.

Fence works best when it can turn various upstream formats into one normalized
tool-call representation before applying policy and validation.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional


@dataclass
class NormalizedToolCall:
    """Unified internal representation for a tool call."""

    agent_id: str
    tool_name: str
    arguments: Dict[str, Any]
    session_id: Optional[str] = None
    provider: str = "generic"
    raw_payload: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ToolCallAdapter:
    """Adapter that normalizes common agent payload formats."""

    def normalize(self, payload: Dict[str, Any], provider: str = "generic") -> NormalizedToolCall:
        provider = provider.lower()
        if provider == "openai":
            return self._normalize_openai(payload)
        if provider == "anthropic":
            return self._normalize_anthropic(payload)
        if provider == "mcp":
            return self._normalize_mcp(payload)
        return self._normalize_generic(payload)

    def _normalize_generic(self, payload: Dict[str, Any]) -> NormalizedToolCall:
        return NormalizedToolCall(
            agent_id=payload["agent_id"],
            tool_name=payload["tool_name"],
            arguments=payload.get("arguments", {}),
            session_id=payload.get("session_id"),
            provider=payload.get("provider", "generic"),
            raw_payload=payload,
        )

    def _normalize_openai(self, payload: Dict[str, Any]) -> NormalizedToolCall:
        tool = payload.get("tool_call", payload)
        return NormalizedToolCall(
            agent_id=payload.get("agent_id", "openai-agent"),
            tool_name=tool.get("name") or tool.get("tool_name"),
            arguments=tool.get("arguments", {}),
            session_id=payload.get("session_id"),
            provider="openai",
            raw_payload=payload,
        )

    def _normalize_anthropic(self, payload: Dict[str, Any]) -> NormalizedToolCall:
        tool = payload.get("tool_use", payload)
        return NormalizedToolCall(
            agent_id=payload.get("agent_id", "anthropic-agent"),
            tool_name=tool.get("name") or tool.get("tool_name"),
            arguments=tool.get("input", tool.get("arguments", {})),
            session_id=payload.get("session_id"),
            provider="anthropic",
            raw_payload=payload,
        )

    def _normalize_mcp(self, payload: Dict[str, Any]) -> NormalizedToolCall:
        call = payload.get("call", payload)
        return NormalizedToolCall(
            agent_id=payload.get("agent_id", "mcp-agent"),
            tool_name=call.get("tool_name") or call.get("name"),
            arguments=call.get("arguments", {}),
            session_id=payload.get("session_id"),
            provider="mcp",
            raw_payload=payload,
        )
