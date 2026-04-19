"""
Minimal real-world integration example for Fence.

This is the pattern most users should copy into their own projects:

1. Build a tool call.
2. Ask Fence whether it is allowed.
3. Execute the tool only if Fence approves.
4. Record the trace id or audit data for observability.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict

from fence_client import FenceClient


FENCE_URL = os.getenv("FENCE_URL", "http://127.0.0.1:8000")
FENCE_API_KEY = os.getenv("FENCE_API_KEY", "dev-key")


def update_crm_record(record_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    """Pretend CRM tool that your own application would replace."""
    return {
        "status": "updated",
        "record_id": record_id,
        "fields": fields,
    }


def draft_support_reply(customer_name: str, issue: str) -> str:
    """Pretend reply generator that could be replaced by any LLM call."""
    return (
        f"Hi {customer_name}, we are investigating the issue: {issue}. "
        "We will update you shortly."
    )


def main() -> None:
    fence = FenceClient(base_url=FENCE_URL, api_key=FENCE_API_KEY)

    ticket = {
        "ticket_id": "TK-2048",
        "customer_name": "Northwind",
        "issue": "Checkout failing in one region",
    }

    tool_call = {
        "agent_id": "support-agent",
        "tool_name": "update_ticket",
        "arguments": {
            "ticket_id": ticket["ticket_id"],
            "fields": {
                "priority": "urgent",
                "status": "in_progress",
            },
            "note": "Fence-approved support triage",
        },
    }

    decision = fence.decide_tool_call(
        agent_id=tool_call["agent_id"],
        tool_name=tool_call["tool_name"],
        arguments=tool_call["arguments"],
        provider="generic",
    )

    print("Fence decision:")
    print(json.dumps(decision.__dict__, indent=2))

    if decision.success:
        crm_result = update_crm_record(
            record_id=ticket["ticket_id"],
            fields=tool_call["arguments"]["fields"],
        )
        print("\nCRM result:")
        print(json.dumps(crm_result, indent=2))

    reply = draft_support_reply(ticket["customer_name"], ticket["issue"])
    print("\nReply:")
    print(reply)


if __name__ == "__main__":
    main()
