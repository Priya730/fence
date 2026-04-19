"""
AutoGen + Ollama demo that routes tool decisions through Fence.

Free path:
- AutoGen orchestrates the agent
- Ollama provides the local model
- Fence acts as the policy gateway before tool execution

No OpenAI key or credit card required.

Prereqs:
- Install Ollama and pull a local model, for example:
    ollama pull llama3.1
- Install AutoGen with Ollama support:
    pip install "pyautogen[ollama]"
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Dict

import httpx


FENCE_URL = os.getenv("FENCE_URL", "http://127.0.0.1:8000")
FENCE_API_KEY = os.getenv("FENCE_API_KEY", "dev-key")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")


async def call_fence(agent_id: str, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Send a tool call to Fence and return the decision."""
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{FENCE_URL}/call",
            headers={"X-API-Key": FENCE_API_KEY},
            json={
                "agent_id": agent_id,
                "tool_name": tool_name,
                "arguments": arguments,
                "provider": "autogen",
            },
        )
        response.raise_for_status()
        return response.json()


async def main() -> None:
    """Run a small AutoGen agent that asks Fence before tool execution."""
    try:
        from autogen_core.models import UserMessage
        from autogen_ext.models.ollama import OllamaChatCompletionClient
    except ImportError as exc:
        raise SystemExit(
            'Install the free local stack first: pip install "pyautogen[ollama]"'
        ) from exc

    print("Fence demo using AutoGen + Ollama")
    print(f"Fence URL: {FENCE_URL}")
    print(f"Ollama model: {OLLAMA_MODEL} at {OLLAMA_HOST}")

    model_client = OllamaChatCompletionClient(model=OLLAMA_MODEL, host=OLLAMA_HOST)

    prompt = (
        "You are a research agent. Before calling any tool, ask Fence if the "
        "call should be allowed. Then write a short response explaining the result."
    )

    fence_decision = await call_fence(
        agent_id="research-agent",
        tool_name="search",
        arguments={"query": "agent safety patterns", "max_results": 3},
    )

    print("\nFence decision:")
    print(json.dumps(fence_decision, indent=2))

    if not fence_decision.get("success"):
        print("\nFence blocked the call, so the agent stops here.")
        return

    response = await model_client.create([UserMessage(content=prompt, source="user")])
    print("\nAutoGen / Ollama response:")
    print(response.content)

    await model_client.close()


if __name__ == "__main__":
    asyncio.run(main())
