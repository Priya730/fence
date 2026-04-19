# Fence

Fence is a policy gateway for AI agent tool calls.

It sits between an agent and the tools it wants to use, and checks:

- is this tool registered?
- is this agent allowed to use it?
- are the arguments valid?
- is this action high-risk?
- should human approval be required?

Fence is built for teams that want agent actions to be controlled, auditable, and easier to integrate.

[![Tests](https://github.com/yourusername/fence/actions/workflows/tests.yml/badge.svg)](https://github.com/yourusername/fence/actions)
[![Code Coverage](https://codecov.io/gh/yourusername/fence/branch/main/graph/badge.svg)](https://codecov.io/gh/yourusername/fence)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## What It Includes

- FastAPI service for runtime decisions
- tool registry and policy enforcement
- Pydantic schema validation
- SQLite persistence for sessions and audit logs
- tiny Python client for integration
- support triage demo agent
- docs, architecture diagrams, and runbook

## Current Status

Fence is a real working prototype, not a finished enterprise platform.

It is useful for:

- learning how agent governance works
- integrating a policy layer into another project
- demonstrating safety checks, validation, and audit logging

It is not yet a full production control plane with multi-tenant auth, Redis, Postgres, sandboxed execution, and policy rollout.

## Quick Start

### 1. Install

Fence targets Python 3.11.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
```

### 2. Start Fence

```bash
export FENCE_API_KEYS="dev-key"
export ENABLE_TELEMETRY=false
python proxy.py
```

Fence will be available at `http://127.0.0.1:8000`.

### 3. Try The Support Agent Demo

In another terminal:

```bash
source .venv/bin/activate
ollama serve
ollama pull llama3.1:latest
export OLLAMA_MODEL=llama3.1:latest
python examples/support_triage_agent.py
```

## Integrate Fence

The easiest integration pattern is:

```python
from fence_client import FenceClient

fence = FenceClient(base_url="http://127.0.0.1:8000", api_key="dev-key")
decision = fence.decide_tool_call(
    agent_id="support-agent",
    tool_name="update_ticket",
    arguments={
        "ticket_id": "TK-1042",
        "fields": {"priority": "urgent"},
    },
)

if decision.success:
    # run the real tool
    pass
```

If your framework already emits provider-shaped payloads, Fence can normalize those too.

## Demos

- [Support triage agent](examples/support_triage_agent.py)
- [Integration example](examples/integration_example.py)
- [AutoGen + Ollama demo](examples/autogen_ollama_fence_demo.py)

## Docs

If you want to learn the project deeply, start here:

- [Build Fence From Zero](docs/BUILD_FROM_ZERO.md)
- [Build the Support Agent From Zero](docs/BUILD_SUPPORT_AGENT.md)
- [Build the SDK Integration From Zero](docs/BUILD_SDK_INTEGRATION.md)
- [Build the Dockerized Deployment From Zero](docs/BUILD_DOCKER_DEPLOYMENT.md)
- [Fence Senior Architecture](docs/ARCHITECTURE_SENIOR.md)
- [Fence Architecture Visuals](docs/ARCHITECTURE_VISUALS.md)
- [What Fence Is](docs/LEARN_FENCE.md)
- [Fence File Guide](docs/FILE_GUIDE.md)
- [Runbook](RUNBOOK.md)
- [Blog draft](BLOG.md)

## API Endpoints

- `GET /health`
- `GET /stats`
- `GET /tools`
- `GET /tools/{tool_name}`
- `GET /policy/{agent_id}`
- `GET /schema/{tool_name}`
- `GET /sessions`
- `GET /sessions/{session_id}`
- `GET /sessions/{session_id}/audit`
- `POST /call`
- `POST /v1/decide`

## Why Fence Exists

LLMs are good at proposing actions.
They are much less trustworthy when those actions touch the real world.

Fence helps by enforcing runtime governance around tool use:

- policy
- validation
- budgets
- auditability
- human approval for risky actions

## Tech Stack

- Python
- FastAPI
- Pydantic
- SQLite
- YAML
- OpenTelemetry
- Ollama for local demo agents

## Repository Layout

```text
proxy.py                  # API server
fence_client.py           # tiny client for integration
safety_guardrails.py      # policy engine
semantic_validator.py     # schema validation
storage.py                # SQLite persistence
adapters.py               # request normalization
budgeting.py              # budget tracking
examples/                 # demos and sample data
docs/                     # tutorials and architecture docs
config/                   # policy and env examples
```

## License

MIT
