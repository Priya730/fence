"""
Advanced Example: More complete walkthrough of Fence.

This script shows the proxy from the perspective of an operator:
- inspect policy metadata
- inspect validation schemas
- run allowed and blocked requests
- inspect lightweight health and stats endpoints
"""

import asyncio
import json

from proxy import app, safety_engine, validator, budget_engine
from budgeting import AgentSession


async def run_advanced_demo() -> None:
    print("=" * 80)
    print("FENCE - ADVANCED DEMO")
    print("=" * 80)

    print("\n[1] Policy metadata")
    print(json.dumps(safety_engine.get_policy_info("research-agent"), indent=2))

    print("\n[2] Schema metadata")
    print(json.dumps(validator.get_schema_info("search"), indent=2))

    print("\n[3] Health snapshot")
    print(
        json.dumps(
            {
                "status": "ready",
                "policies_loaded": len(safety_engine.policies),
                "active_sessions": 0,
                "routes": [route.path for route in app.routes if getattr(route, "path", None)],
            },
            indent=2,
        )
    )

    session = AgentSession(
        session_id="advanced-demo-session",
        agent_id="research-agent",
        token_budget=2_000,
        cost_budget=0.25,
        timeout_minutes=15,
    )

    print("\n[4] Allowed request")
    allowed = safety_engine.check_policy(
        agent_id="research-agent",
        tool_name="search",
        arguments={"query": "agent safety patterns", "role": "analyst"},
    )
    print(json.dumps(allowed, indent=2))

    print("\n[5] Blocked request")
    blocked = safety_engine.check_policy(
        agent_id="research-agent",
        tool_name="execute_shell",
        arguments={
            "command": "rm -rf /tmp/users",
            "cwd": "/tmp",
            "timeout_seconds": 5,
            "human_approved": True,
            "role": "analyst",
        },
    )
    print(json.dumps(blocked, indent=2))

    print("\n[6] Budget snapshot")
    budget_engine.record_usage(session, tokens=250, cost=0.002)
    print(json.dumps(budget_engine.get_session_summary(session), indent=2))

    print("\n[7] Validation feedback")
    invalid = validator.validate("search", {"max_results": 5})
    print(json.dumps(
        {
            "is_valid": invalid.is_valid,
            "errors": invalid.errors,
            "corrective_guidance": invalid.corrective_guidance,
        },
        indent=2,
    ))

    print("\nAdvanced demo complete.")


if __name__ == "__main__":
    asyncio.run(run_advanced_demo())
