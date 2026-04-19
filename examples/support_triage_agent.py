"""
Fence support triage agent.

This is a real agent loop:
- it reads a ticket
- it asks the model for the next action
- it asks Fence before every action
- it executes only approved actions
- it records artifacts for the steps it took
- it shows one deliberate rejection path

It is free to run locally with Ollama, but it can still fall back to a
deterministic planner if the model is unavailable.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from semantic_validator import SemanticValidator


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
ARTIFACTS_DIR = ROOT / "artifacts"
ARTIFACTS_DIR.mkdir(exist_ok=True)

FENCE_URL = os.getenv("FENCE_URL", "http://127.0.0.1:8000")
FENCE_API_KEY = os.getenv("FENCE_API_KEY", "dev-key")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:latest")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")

DEFAULT_TICKET_PATH = DATA_DIR / "support_ticket.json"
DEFAULT_KB_PATH = DATA_DIR / "knowledge_base.md"
SEMANTIC_VALIDATOR = SemanticValidator()


def load_ticket(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_kb(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def schema_hint(tool_name: str) -> str:
    """Build a compact schema summary for the model prompt."""
    info = SEMANTIC_VALIDATOR.get_schema_info(tool_name)
    if "error" in info:
        return info["error"]
    lines = []
    for field_name, field_meta in info["fields"].items():
        required = "required" if field_meta["required"] else "optional"
        description = field_meta["description"] or ""
        lines.append(f"- {field_name} ({required}): {description}")
    return "\n".join(lines)


def search_kb(query: str, kb_text: str, top_k: int = 3) -> List[str]:
    """Tiny local search over the knowledge base."""
    scored: List[str] = []
    query_terms = {part.lower() for part in query.split() if part.strip()}
    for block in kb_text.split("\n\n"):
        if not block.strip():
            continue
        score = sum(1 for term in query_terms if term in block.lower())
        if score:
            scored.append(block.strip())
    return scored[:top_k]


async def write_artifact(name: str, data: Dict[str, Any]) -> Path:
    path = ARTIFACTS_DIR / name
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


async def call_fence(agent_id: str, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Ask Fence if a tool call is allowed."""
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{FENCE_URL}/call",
            headers={"X-API-Key": FENCE_API_KEY},
            json={
                "agent_id": agent_id,
                "tool_name": tool_name,
                "arguments": arguments,
                "provider": "support-agent",
            },
        )
        response.raise_for_status()
        return response.json()


async def ollama_available() -> bool:
    """Check whether Ollama is reachable."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(f"{OLLAMA_HOST}/api/tags")
            response.raise_for_status()
            return True
    except Exception:
        return False


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    """Best-effort JSON extraction from model output."""
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    cleaned = cleaned.strip().strip("`").strip()
    try:
        return json.loads(cleaned)
    except Exception:
        match = re.search(r"\{.*\}", cleaned, flags=re.S)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except Exception:
            return None


def build_draft_reply_arguments(state: Dict[str, Any], provided: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Coerce a draft_reply action into the Fence schema."""
    provided = provided or {}
    ticket = state["ticket"]
    next_steps = provided.get("next_steps")
    if not isinstance(next_steps, list) or not next_steps:
        next_steps = [
            "Investigating gateway health and certificate changes",
            "Escalated to on-call due to enterprise impact",
        ]

    summary = provided.get("summary") or ticket.get("subject", "Support incident")

    return {
        "ticket_id": provided.get("ticket_id") or ticket["ticket_id"],
        "customer_name": provided.get("customer_name") or ticket["customer_name"],
        "summary": summary,
        "next_steps": next_steps,
    }


async def ollama_json(prompt: str) -> Optional[Dict[str, Any]]:
    """Ask the local model for structured JSON output."""
    async with httpx.AsyncClient(timeout=120) as client:
        for endpoint, payload in (
            (
                "chat",
                {
                    "model": OLLAMA_MODEL,
                    "format": "json",
                    "messages": [
                        {"role": "system", "content": "Return valid JSON only."},
                        {"role": "user", "content": prompt},
                    ],
                    "stream": False,
                },
            ),
            (
                "generate",
                {
                    "model": OLLAMA_MODEL,
                    "format": "json",
                    "prompt": f"Return valid JSON only.\n\n{prompt}",
                    "stream": False,
                },
            ),
        ):
            try:
                response = await client.post(f"{OLLAMA_HOST}/api/{endpoint}", json=payload)
                response.raise_for_status()
                data = response.json()
                text = data["message"]["content"] if endpoint == "chat" else data["response"]
                parsed = _extract_json(text)
                if parsed is not None:
                    return parsed
            except Exception:
                continue
    return None


def build_fallback_action(state: Dict[str, Any]) -> Dict[str, Any]:
    """Deterministic action selection if the model is unavailable."""
    if not state["kb_hits"]:
        return {
            "tool_name": "search_kb",
            "arguments": {
                "query": "payment failures after deployments",
                "top_k": 2,
            },
        }
    if not state["escalated"]:
        return {
            "tool_name": "escalate_ticket",
            "arguments": {
                "ticket_id": state["ticket"]["ticket_id"],
                "severity": "high",
                "reason": "Payment incident affecting enterprise customers after deployment.",
            },
        }
    if not state["reply"]:
        return {
            "tool_name": "draft_reply",
            "arguments": {
                "ticket_id": state["ticket"]["ticket_id"],
                "customer_name": state["ticket"]["customer_name"],
                "summary": state["ticket"]["subject"],
                "next_steps": [
                    "Investigating gateway health and certificate changes",
                    "Escalated to on-call due to enterprise impact",
                ],
            },
        }
    if not state["ticket_updated"]:
        return {
            "tool_name": "update_ticket",
            "arguments": {
                "ticket_id": state["ticket"]["ticket_id"],
                "fields": {"priority": "urgent", "status": "in_progress"},
                "note": "Fence-approved triage update",
            },
        }
    return {"tool_name": "finish", "arguments": {}}


async def choose_next_action(state: Dict[str, Any], kb_text: str) -> Dict[str, Any]:
    """Ask the model for the next best action, falling back if needed."""
    prompt = json.dumps(
        {
            "ticket": state["ticket"],
            "knowledge_base": kb_text,
            "state": {
                "kb_hits": state["kb_hits"],
                "escalated": state["escalated"],
                "reply_exists": bool(state["reply"]),
                "ticket_updated": state["ticket_updated"],
                "steps_taken": state["steps_taken"],
            },
            "allowed_tools": [
                "search_kb",
                "draft_reply",
                "escalate_ticket",
                "update_ticket",
                "finish",
            ],
            "tool_schemas": {
                "search_kb": schema_hint("search_kb"),
                "draft_reply": schema_hint("draft_reply"),
                "escalate_ticket": schema_hint("escalate_ticket"),
                "update_ticket": schema_hint("update_ticket"),
            },
            "workflow_rules": [
                "Prefer search_kb before drafting the customer reply.",
                "Use draft_reply only after you have enough context to write a summary.",
                "Always return the next single action only.",
                "For draft_reply, return ticket_id, customer_name, summary, and optional next_steps.",
            ],
            "instruction": (
                "Return JSON with fields tool_name and arguments. "
                "Choose exactly one next action. "
                "Use finish when the work is done. "
                "Do not include any commentary."
            ),
        },
        indent=2,
    )

    if await ollama_available():
        parsed = await ollama_json(prompt)
        if isinstance(parsed, dict) and parsed.get("tool_name"):
            if parsed["tool_name"] == "draft_reply":
                parsed["arguments"] = build_draft_reply_arguments(state, parsed.get("arguments"))
            return {
                "tool_name": parsed["tool_name"],
                "arguments": parsed.get("arguments", {}),
            }

    return build_fallback_action(state)


async def generate_reply(ticket: Dict[str, Any], kb_hits: List[str], state: Dict[str, Any]) -> Dict[str, Any]:
    """Generate the customer-facing reply."""
    prompt = json.dumps(
        {
            "ticket": ticket,
            "knowledge_hits": kb_hits,
            "state": state,
            "instruction": (
                "Return JSON with fields reply and internal_summary. "
                "Reply should be concise, factual, and empathetic."
            ),
        },
        indent=2,
    )

    if await ollama_available():
        parsed = await ollama_json(prompt)
        if isinstance(parsed, dict) and parsed.get("reply"):
            parsed.setdefault("internal_summary", "Reply generated by Ollama.")
            return parsed

    return {
        "reply": (
            f"Hi {ticket['customer_name']}, we are investigating the payment issue "
            "and will update you shortly."
        ),
        "internal_summary": "Fallback reply generated without Ollama.",
    }


async def execute_action(
    action: Dict[str, Any],
    state: Dict[str, Any],
    kb_text: str,
) -> None:
    """Execute an approved action."""
    tool_name = action["tool_name"]
    arguments = action.get("arguments", {})

    if tool_name == "draft_reply":
        repaired = build_draft_reply_arguments(state, arguments)
        if repaired != arguments:
            print("Repaired draft_reply arguments to match Fence schema")
            arguments = repaired

    fence_decision = await call_fence("support-agent", tool_name, arguments)
    print(f"\nFence decision for {tool_name}: {fence_decision['decision']}")

    if not fence_decision.get("success"):
        print(json.dumps(fence_decision, indent=2))
        state["steps_taken"].append(
            {
                "tool_name": tool_name,
                "decision": "blocked",
                "error": fence_decision.get("error"),
            }
        )
        return

    if tool_name == "search_kb":
        kb_hits = search_kb(arguments["query"], kb_text, arguments.get("top_k", 3))
        state["kb_hits"] = kb_hits
        state["steps_taken"].append(
            {"tool_name": tool_name, "decision": "allowed", "result_count": len(kb_hits)}
        )
        print(json.dumps(kb_hits, indent=2))
        return

    if tool_name == "escalate_ticket":
        escalation = {
            "ticket_id": arguments["ticket_id"],
            "severity": arguments["severity"],
            "reason": arguments["reason"],
            "status": "paged_on_call",
        }
        path = await write_artifact(f"{state['ticket']['ticket_id']}_escalation.json", escalation)
        state["escalated"] = True
        state["steps_taken"].append(
            {"tool_name": tool_name, "decision": "allowed", "artifact": str(path)}
        )
        print(f"Escalation written to {path}")
        return

    if tool_name == "draft_reply":
        reply_payload = await generate_reply(state["ticket"], state["kb_hits"], state)
        state["reply"] = reply_payload
        state["steps_taken"].append(
            {
                "tool_name": tool_name,
                "decision": "allowed",
                "model_driven": reply_payload.get("internal_summary") != "Fallback reply generated without Ollama.",
            }
        )
        print(json.dumps(reply_payload, indent=2))
        return

    if tool_name == "update_ticket":
        update = {
            "ticket_id": arguments["ticket_id"],
            "fields": arguments["fields"],
            "note": arguments.get("note", ""),
        }
        path = await write_artifact(f"{state['ticket']['ticket_id']}_ticket_update.json", update)
        state["ticket_updated"] = True
        state["steps_taken"].append(
            {"tool_name": tool_name, "decision": "allowed", "artifact": str(path)}
        )
        print(f"Ticket update written to {path}")
        return

    raise ValueError(f"Unknown tool: {tool_name}")


async def demonstrate_rejection() -> None:
    """Show Fence rejecting a real high-risk capability for this agent."""
    print("\nRejection demo")
    bad_call = await call_fence(
        "support-agent",
        "execute_shell",
        {
            "command": "rm -rf /tmp/customer-data",
            "cwd": "/tmp",
            "timeout_seconds": 5,
        },
    )
    print(json.dumps(bad_call, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fence support triage agent")
    parser.add_argument("--ticket-file", type=Path, default=DEFAULT_TICKET_PATH)
    parser.add_argument("--kb-file", type=Path, default=DEFAULT_KB_PATH)
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    ticket = load_ticket(args.ticket_file)
    kb_text = load_kb(args.kb_file)

    print("Fence support triage demo")
    print(f"Ticket: {ticket['ticket_id']} - {ticket['subject']}")
    print(f"Fence URL: {FENCE_URL}")
    print(f"Model: {OLLAMA_MODEL} at {OLLAMA_HOST}")

    state: Dict[str, Any] = {
        "ticket": ticket,
        "kb_hits": [],
        "escalated": False,
        "reply": {},
        "ticket_updated": False,
        "steps_taken": [],
    }

    for _ in range(5):
        action = await choose_next_action(state, kb_text)
        if action["tool_name"] == "finish":
            break
        await execute_action(action, state, kb_text)

    # Make the rejection visible in every demo.
    await demonstrate_rejection()

    if state["reply"]:
        final_payload = state["reply"]
    else:
        final_payload = {
            "reply": (
                f"Hi {ticket['customer_name']}, we found a likely payment issue "
                "and escalated it for immediate investigation."
            ),
            "internal_summary": "Ticket triaged and escalated.",
        }

    print("\nSteps taken")
    print(json.dumps(state["steps_taken"], indent=2))

    print("\nFinal customer reply")
    print(final_payload["reply"])
    print("\nInternal summary")
    print(final_payload.get("internal_summary", ""))

    await write_artifact(
        f"{ticket['ticket_id']}_final_summary.json",
        {
            "ticket": ticket,
            "state": state,
            "final_payload": final_payload,
        },
    )


if __name__ == "__main__":
    asyncio.run(main())
