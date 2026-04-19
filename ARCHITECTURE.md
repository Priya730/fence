# Fence Architecture

Fence is a control layer that sits between an AI agent and the tools it wants to use.

## Request Flow

```text
Agent -> Fence API -> Policy -> Validation -> Budget -> Audit -> Decision -> Tool
```

## Main Components

1. **FastAPI API**
   - receives tool-call requests
   - returns allowed or blocked decisions

2. **Tool Registry**
   - declares which tools exist
   - assigns capability metadata and risk level

3. **Policy Engine**
   - checks allowlists, blocked operations, RBAC, and approval rules

4. **Schema Validator**
   - checks tool arguments using Pydantic

5. **Budget Engine**
   - tracks token and cost budgets per session

6. **Storage Layer**
   - persists sessions and audit logs in SQLite

7. **Client SDK**
   - makes integration into other apps simpler

## Why This Shape

Fence is designed to be:

- simple to integrate
- easy to reason about
- useful for local development
- honest about what is allowed and what is blocked

The current stack uses SQLite for persistence, which keeps the project lightweight and easy to run locally.

