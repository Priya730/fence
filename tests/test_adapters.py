"""Tests for normalization adapters."""

from adapters import ToolCallAdapter


def test_normalize_generic_call():
    adapter = ToolCallAdapter()
    call = adapter.normalize(
        {
            "agent_id": "research-agent",
            "tool_name": "search",
            "arguments": {"query": "Fence"},
            "session_id": "abc",
        }
    )

    assert call.agent_id == "research-agent"
    assert call.tool_name == "search"
    assert call.arguments["query"] == "Fence"
    assert call.session_id == "abc"


def test_normalize_openai_call():
    adapter = ToolCallAdapter()
    call = adapter.normalize(
        {
            "agent_id": "openai-agent",
            "tool_call": {
                "name": "summarize",
                "arguments": {"content": "hello world"},
            },
        },
        provider="openai",
    )

    assert call.provider == "openai"
    assert call.tool_name == "summarize"
    assert call.arguments["content"] == "hello world"
