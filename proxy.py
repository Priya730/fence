"""
Fence: a tool-call policy gateway for agentic systems.

Fence normalizes tool calls from different agent frameworks, enforces policy,
validates arguments, tracks budgets, persists audit events, and returns a
decision that upstream agents can use before executing real tools.
"""

from __future__ import annotations

import logging
import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from adapters import NormalizedToolCall, ToolCallAdapter
from budgeting import AgentSession, BudgetCheckResult, BudgetEngine
from observability import get_tracer, setup_telemetry
from safety_guardrails import SafetyEngine
from schemas import ValidationResult
from semantic_validator import SemanticValidator
from storage import FenceStore

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


APP_NAME = "Fence"
APP_DESCRIPTION = "Policy gateway for LLM tool calls with safety, validation, budgets, and audit logs"
DEFAULT_TOKEN_BUDGET = int(os.getenv("FENCE_DEFAULT_TOKEN_BUDGET", "100000"))
DEFAULT_COST_BUDGET = float(os.getenv("FENCE_DEFAULT_COST_BUDGET", "10.0"))
DEFAULT_TIMEOUT_MINUTES = int(os.getenv("FENCE_DEFAULT_TIMEOUT_MINUTES", "60"))
DB_PATH = os.getenv("FENCE_DB_PATH", "fence.db")
API_KEYS = {key.strip() for key in os.getenv("FENCE_API_KEYS", "").split(",") if key.strip()}

policy_path = Path(__file__).resolve().parent / "config" / "safety_policies.yaml"

app = FastAPI(
    title=APP_NAME,
    description=APP_DESCRIPTION,
    version="2.0.0",
)

safety_engine = SafetyEngine(policy_file=str(policy_path))
validator = SemanticValidator()
budget_engine = BudgetEngine()
adapter = ToolCallAdapter()
store = FenceStore(db_path=DB_PATH)
tracer = get_tracer(__name__)

_sessions: Dict[str, AgentSession] = {}


class ToolCallRequest(BaseModel):
    """Normalized request shape for direct tool-call proxies."""

    agent_id: str
    tool_name: str
    arguments: Dict[str, Any]
    session_id: Optional[str] = None
    provider: str = "generic"
    token_budget: Optional[int] = None
    cost_budget: Optional[float] = None
    timeout_minutes: Optional[int] = None


class ToolDecisionRequest(BaseModel):
    """Provider-shaped envelope that Fence can normalize first."""

    provider: str = "generic"
    payload: Dict[str, Any]


class ToolDecisionResponse(BaseModel):
    """Decision returned by Fence."""

    success: bool
    trace_id: str
    decision: str
    normalized_call: Dict[str, Any] = Field(default_factory=dict)
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SessionResponse(BaseModel):
    """Serialized session state."""

    session_id: str
    agent_id: str
    status: str
    created_at: str
    expires_at: str
    timeout_minutes: int
    tokens_used: int
    token_budget: int
    cost_used: float
    cost_budget: float


class AuditEventResponse(BaseModel):
    """Persisted audit event."""

    event_id: str
    session_id: str
    agent_id: str
    tool_name: str
    decision: str
    reason: str
    created_at: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ToolDefinitionResponse(BaseModel):
    """Declared tool capability."""

    name: str
    description: str = ""
    category: str = "general"
    risk_level: str = "low"
    approval_required: bool = False
    blocked_argument_patterns: List[str] = Field(default_factory=list)
    allowed_argument_keys: List[str] = Field(default_factory=list)


def _require_api_key(x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")) -> None:
    """Optionally enforce an API key when Fence is configured for auth."""
    if not API_KEYS:
        return

    if not x_api_key or x_api_key not in API_KEYS:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


@app.on_event("startup")
async def startup() -> None:
    """Initialize observability when the service boots."""
    setup_telemetry(service_name=APP_NAME.lower())
    logger.info("%s started", APP_NAME)


@app.get("/health")
async def health_check() -> Dict[str, Any]:
    """Health endpoint for orchestration and load balancers."""
    expired_sessions = _cleanup_sessions()
    return {
        "status": "ok",
        "service": APP_NAME.lower(),
        "sessions": len(_sessions),
        "expired_sessions_removed": expired_sessions,
        "policies_loaded": len(safety_engine.policies),
        "registered_tools": len(safety_engine.tool_registry),
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


@app.get("/policy/{agent_id}")
async def get_policy(agent_id: str, _: None = Depends(_require_api_key)) -> Dict[str, Any]:
    """Expose the resolved policy for a given agent."""
    return safety_engine.get_policy_info(agent_id)


@app.get("/schema/{tool_name}")
async def get_schema(tool_name: str, _: None = Depends(_require_api_key)) -> Dict[str, Any]:
    """Expose the schema metadata used by the validator."""
    return validator.get_schema_info(tool_name)


@app.get("/tools", response_model=List[ToolDefinitionResponse])
async def list_tools(_: None = Depends(_require_api_key)) -> List[ToolDefinitionResponse]:
    """Expose the declared tool registry."""
    return [ToolDefinitionResponse(**tool) for tool in safety_engine.list_tools()]


@app.get("/tools/{tool_name}", response_model=ToolDefinitionResponse)
async def get_tool(tool_name: str, _: None = Depends(_require_api_key)) -> ToolDefinitionResponse:
    """Expose a single declared tool."""
    tool = safety_engine.get_tool_info(tool_name)
    if "error" in tool:
        raise HTTPException(status_code=404, detail=tool["error"])
    return ToolDefinitionResponse(**tool)


@app.get("/sessions", response_model=List[SessionResponse])
async def list_sessions(_: None = Depends(_require_api_key)) -> List[SessionResponse]:
    """List all persisted sessions."""
    return [_session_response_from_row(row) for row in store.list_sessions()]


@app.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session_info(session_id: str, _: None = Depends(_require_api_key)) -> SessionResponse:
    """Fetch a specific session."""
    row = store.get_session(session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return _session_response_from_row(row)


@app.get("/sessions/{session_id}/audit", response_model=List[AuditEventResponse])
async def get_session_audit(session_id: str, _: None = Depends(_require_api_key)) -> List[AuditEventResponse]:
    """Fetch audit trail for a session."""
    events = store.list_audit_events(session_id=session_id)
    return [AuditEventResponse(**_normalize_audit_row(event)) for event in events]


@app.post("/call", response_model=ToolDecisionResponse)
async def proxy_tool_call(req: ToolCallRequest, _: None = Depends(_require_api_key)) -> ToolDecisionResponse:
    """Proxy a normalized tool call through Fence."""
    call = NormalizedToolCall(
        agent_id=req.agent_id,
        tool_name=req.tool_name,
        arguments=req.arguments,
        session_id=req.session_id,
        provider=req.provider,
    )
    return await _process_normalized_call(call, req.token_budget, req.cost_budget, req.timeout_minutes)


@app.post("/v1/decide", response_model=ToolDecisionResponse)
async def decide_tool_call(req: ToolDecisionRequest, _: None = Depends(_require_api_key)) -> ToolDecisionResponse:
    """Accept provider-shaped payloads and normalize them before enforcement."""
    call = adapter.normalize(req.payload, provider=req.provider)
    return await _process_normalized_call(call)


@app.get("/stats")
async def get_stats(_: None = Depends(_require_api_key)) -> Dict[str, Any]:
    """Return lightweight operational stats."""
    _cleanup_sessions()
    return {
        "sessions": len(_sessions),
        "validation": validator.get_stats(),
        "policies": len(safety_engine.policies),
        "tools": len(safety_engine.tool_registry),
        "audit_events": len(store.list_audit_events()),
    }


@app.delete("/sessions/{session_id}")
async def clear_session(session_id: str, _: None = Depends(_require_api_key)) -> Dict[str, Any]:
    """Delete a session and its in-memory mirror."""
    deleted = store.delete_session(session_id)
    _sessions.pop(session_id, None)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"message": f"Session {session_id} cleared"}


async def _process_normalized_call(
    call: NormalizedToolCall,
    token_budget: Optional[int] = None,
    cost_budget: Optional[float] = None,
    timeout_minutes: Optional[int] = None,
) -> ToolDecisionResponse:
    trace_id = str(uuid.uuid4())

    with tracer.start_as_current_span("fence_decision") as span:
        span.set_attribute("agent_id", call.agent_id)
        span.set_attribute("tool_name", call.tool_name)
        span.set_attribute("provider", call.provider)
        span.set_attribute("trace_id", trace_id)

        try:
            session = _get_or_create_session(
                agent_id=call.agent_id,
                session_id=call.session_id,
                token_budget=token_budget,
                cost_budget=cost_budget,
                timeout_minutes=timeout_minutes,
            )

            safety_result = safety_engine.check_policy(
                agent_id=call.agent_id,
                tool_name=call.tool_name,
                arguments=call.arguments,
            )
            if not safety_result["allowed"]:
                return _finalize_decision(
                    trace_id=trace_id,
                    call=call,
                    session=session,
                    decision="blocked",
                    error=safety_result["reason"],
                    metadata={"stage": "safety_check"},
                    span=span,
                )

            validation_result = validator.validate(call.tool_name, call.arguments)
            if not validation_result.is_valid:
                return _finalize_decision(
                    trace_id=trace_id,
                    call=call,
                    session=session,
                    decision="blocked",
                    error=f"Schema validation failed: {validation_result.errors}",
                    metadata={
                        "stage": "semantic_validation",
                        "corrective_guidance": validation_result.corrective_guidance,
                    },
                    span=span,
                )

            budget_result = budget_engine.check_budget(session, estimated_tokens=_estimate_tokens(call.tool_name))
            if not budget_result.allowed:
                return _finalize_decision(
                    trace_id=trace_id,
                    call=call,
                    session=session,
                    decision="blocked",
                    error=budget_result.reason,
                    metadata={"stage": "budget_check"},
                    span=span,
                )

            result = _build_execution_preview(call, session, validation_result, budget_result)
            budget_engine.record_usage(session, tokens=result["tokens_estimated"], cost=result["cost_estimated"])
            store.update_usage(session.session_id, session.tokens_used, session.cost_used)
            store.record_audit_event(
                event_id=str(uuid.uuid4()),
                session_id=session.session_id,
                agent_id=session.agent_id,
                tool_name=call.tool_name,
                decision="allowed",
                reason="All checks passed",
                metadata={
                    "provider": call.provider,
                    "trace_id": trace_id,
                    "tokens_estimated": result["tokens_estimated"],
                    "cost_estimated": result["cost_estimated"],
                },
            )

            span.set_attribute("decision", "allowed")
            return ToolDecisionResponse(
                success=True,
                trace_id=trace_id,
                decision="allowed",
                normalized_call=call.to_dict(),
                result=result,
                metadata={
                    "session_id": session.session_id,
                    "tokens_used": result["tokens_estimated"],
                    "cost": result["cost_estimated"],
                    "provider": call.provider,
                },
            )

        except Exception as exc:
            logger.error("Fence error: %s", exc, exc_info=True)
            store.record_audit_event(
                event_id=str(uuid.uuid4()),
                session_id=call.session_id or "unknown",
                agent_id=call.agent_id,
                tool_name=call.tool_name,
                decision="error",
                reason=str(exc),
                metadata={"provider": call.provider, "trace_id": trace_id},
            )
            span.set_attribute("decision", "error")
            return ToolDecisionResponse(
                success=False,
                trace_id=trace_id,
                decision="error",
                normalized_call=call.to_dict(),
                error=str(exc),
                metadata={"stage": "exception", "provider": call.provider},
            )


def _finalize_decision(
    trace_id: str,
    call: NormalizedToolCall,
    session: AgentSession,
    decision: str,
    error: Optional[str],
    metadata: Dict[str, Any],
    span,
) -> ToolDecisionResponse:
    store.record_audit_event(
        event_id=str(uuid.uuid4()),
        session_id=session.session_id,
        agent_id=session.agent_id,
        tool_name=call.tool_name,
        decision=decision,
        reason=error or "",
        metadata={"provider": call.provider, "trace_id": trace_id, **metadata},
    )
    span.set_attribute("decision", decision)
    return ToolDecisionResponse(
        success=False,
        trace_id=trace_id,
        decision=decision,
        normalized_call=call.to_dict(),
        error=error,
        metadata=metadata | {"session_id": session.session_id, "provider": call.provider},
    )


def _get_or_create_session(
    agent_id: str,
    session_id: Optional[str] = None,
    token_budget: Optional[int] = None,
    cost_budget: Optional[float] = None,
    timeout_minutes: Optional[int] = None,
) -> AgentSession:
    """Return an active session, restoring from SQLite when possible."""
    with tracer.start_as_current_span("session_lookup"):
        active_session_id = session_id or str(uuid.uuid4())
        cached = _sessions.get(active_session_id)
        if cached and not cached.is_expired:
            return cached

        row = store.get_session(active_session_id)
        if row is not None:
            session = _session_from_row(row)
            if not session.is_expired:
                _sessions[active_session_id] = session
                return session
            store.delete_session(active_session_id)

        session = AgentSession(
            session_id=active_session_id,
            agent_id=agent_id,
            token_budget=token_budget or DEFAULT_TOKEN_BUDGET,
            cost_budget=cost_budget or DEFAULT_COST_BUDGET,
            timeout_minutes=timeout_minutes or DEFAULT_TIMEOUT_MINUTES,
        )
        _sessions[session.session_id] = session
        store.upsert_session(
            session_id=session.session_id,
            agent_id=session.agent_id,
            created_at=session.created_at,
            expires_at=session.expires_at,
            timeout_minutes=session.timeout_minutes,
            token_budget=session.token_budget,
            cost_budget=session.cost_budget,
            tokens_used=session.tokens_used,
            cost_used=session.cost_used,
            metadata={"source": "fence"},
        )
        return session


def _cleanup_sessions() -> int:
    """Remove expired sessions from memory and SQLite."""
    expired = [session_id for session_id, session in _sessions.items() if session.is_expired]
    for session_id in expired:
        _sessions.pop(session_id, None)
        store.delete_session(session_id)
    return len(expired)


def _build_execution_preview(
    call: NormalizedToolCall,
    session: AgentSession,
    validation_result: ValidationResult,
    budget_result: BudgetCheckResult,
) -> Dict[str, Any]:
    """Build a deterministic execution preview for real agents."""
    tokens_estimated = _estimate_tokens(call.tool_name)
    cost_estimated = round(tokens_estimated * 0.000002, 6)
    return {
        "status": "approved",
        "tool": call.tool_name,
        "agent_id": call.agent_id,
        "provider": call.provider,
        "session_id": session.session_id,
        "validated_arguments": validation_result.validated_data or call.arguments,
        "budget": {
            "allowed": budget_result.allowed,
            "tokens_used": session.tokens_used,
            "tokens_remaining": session.tokens_remaining,
            "cost_used": session.cost_used,
            "cost_remaining": session.cost_remaining,
        },
        "tokens_estimated": tokens_estimated,
        "cost_estimated": cost_estimated,
    }


def _estimate_tokens(tool_name: str) -> int:
    """Estimate token usage for a tool call based on its shape."""
    return budget_engine.estimate_tokens_for_operation(tool_name)


def _session_from_row(row: Dict[str, Any]) -> AgentSession:
    session = AgentSession(
        session_id=row["session_id"],
        agent_id=row["agent_id"],
        token_budget=row["token_budget"],
        cost_budget=row["cost_budget"],
        timeout_minutes=row["timeout_minutes"],
        created_at=datetime.fromisoformat(row["created_at"]),
        tokens_used=row["tokens_used"],
        cost_used=row["cost_used"],
    )
    return session


def _session_response_from_row(row: Dict[str, Any]) -> SessionResponse:
    session = _session_from_row(row)
    return SessionResponse(
        session_id=session.session_id,
        agent_id=session.agent_id,
        status="active" if not session.is_expired else "expired",
        created_at=session.created_at.isoformat(),
        expires_at=session.expires_at.isoformat(),
        timeout_minutes=session.timeout_minutes,
        tokens_used=session.tokens_used,
        token_budget=session.token_budget,
        cost_used=session.cost_used,
        cost_budget=session.cost_budget,
    )


def _normalize_audit_row(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "event_id": row["event_id"],
        "session_id": row["session_id"],
        "agent_id": row["agent_id"],
        "tool_name": row["tool_name"],
        "decision": row["decision"],
        "reason": row["reason"],
        "created_at": row["created_at"],
        "metadata": json.loads(row["metadata"] or "{}"),
    }


def main() -> None:
    """Run the API locally."""
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "uvicorn is not installed. Run `pip install -r requirements.txt` first."
        ) from exc

    uvicorn.run("proxy:app", host="0.0.0.0", port=8000, reload=False, log_level="info")


if __name__ == "__main__":
    main()
