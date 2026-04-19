"""
Safety Guardrails Engine: Policy enforcement for LLM tool calls
Implements role-based access control (RBAC) and operation blocking
"""

import logging
import re
import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


@dataclass
class SafetyPolicy:
    """Policy definition for an agent"""
    agent_id: str
    allowed_tools: List[str]
    blocked_operations: List[str]
    rate_limits: Dict[str, int]
    rbac_roles: Dict[str, List[str]]
    approval_threshold: str = "high"


@dataclass
class ToolDefinition:
    """Declared capability in the Fence tool registry."""

    name: str
    description: str = ""
    category: str = "general"
    risk_level: str = "low"
    approval_required: bool = False
    blocked_argument_patterns: List[str] = field(default_factory=list)
    allowed_argument_keys: List[str] = field(default_factory=list)


class SafetyEngine:
    """
    Enforces deterministic safety guardrails on tool calls.
    
    Features:
    - Tool allowlisting/blocklisting
    - Blocked operation detection
    - Rate limiting per agent
    - Role-based access control (RBAC)
    """
    
    def __init__(self, policy_file: str = None):
        self.policies: Dict[str, SafetyPolicy] = {}
        self.tool_registry: Dict[str, ToolDefinition] = self._default_tool_registry()
        self.call_history: Dict[str, List[datetime]] = {}
        self._default_policy = SafetyPolicy(
            agent_id="default",
            allowed_tools=["*"],  # Allow all unless config says otherwise
            blocked_operations=["execute_shell"],
            rate_limits={"calls_per_minute": 60},
            rbac_roles={}
        )
        
        if policy_file:
            policy_path = Path(policy_file)
            if not policy_path.exists():
                fallback_candidates = [
                    Path(__file__).resolve().parent / policy_file,
                    Path(__file__).resolve().parent / policy_path.name,
                ]
                for candidate in fallback_candidates:
                    if candidate.exists():
                        policy_path = candidate
                        break
            self._load_policies(str(policy_path))
        
    def _load_policies(self, policy_file: str):
        """Load policies from YAML file"""
        try:
            with open(policy_file, 'r') as f:
                config = yaml.safe_load(f)
            config = config or {}

            defaults = config.get("defaults", {}) if config else {}
            self._default_policy = SafetyPolicy(
                agent_id="default",
                allowed_tools=defaults.get("allowed_tools", ["*"]),
                blocked_operations=defaults.get(
                    "blocked_operations",
                    ["execute_shell"]
                ),
                rate_limits=defaults.get("rate_limits", {"calls_per_minute": 60}),
                rbac_roles=defaults.get("rbac", {}),
                approval_threshold=defaults.get("approval_threshold", "high")
            )

            registry_config = config.get("tool_registry", {})
            if registry_config:
                self.tool_registry = self._load_tool_registry(registry_config)
            
            for agent_id, policy_config in config.get("policies", {}).items():
                self.policies[agent_id] = SafetyPolicy(
                    agent_id=agent_id,
                    allowed_tools=policy_config.get(
                        "allowed_tools",
                        self._default_policy.allowed_tools
                    ),
                    blocked_operations=policy_config.get(
                        "blocked_operations",
                        self._default_policy.blocked_operations
                    ),
                    rate_limits=policy_config.get(
                        "rate_limits",
                        self._default_policy.rate_limits
                    ),
                    rbac_roles=policy_config.get(
                        "rbac",
                        self._default_policy.rbac_roles
                    ),
                    approval_threshold=policy_config.get(
                        "approval_threshold",
                        self._default_policy.approval_threshold
                    )
                )
            logger.info(f"Loaded {len(self.policies)} safety policies")
        except FileNotFoundError:
            logger.warning(f"Policy file not found: {policy_file}")
        except Exception as e:
            logger.error(f"Failed to load policies: {str(e)}")

    def _default_tool_registry(self) -> Dict[str, ToolDefinition]:
        """Built-in registry so Fence can run safely even without YAML extras."""
        return {
            "search": ToolDefinition(
                name="search",
                description="Search a knowledge base or document store",
                category="read",
                risk_level="low",
            ),
            "fetch_document": ToolDefinition(
                name="fetch_document",
                description="Fetch a known document by identifier",
                category="read",
                risk_level="low",
            ),
            "summarize": ToolDefinition(
                name="summarize",
                description="Summarize text content",
                category="read",
                risk_level="low",
            ),
            "analyze": ToolDefinition(
                name="analyze",
                description="Analyze structured data",
                category="compute",
                risk_level="low",
            ),
            "translate": ToolDefinition(
                name="translate",
                description="Translate text between languages",
                category="read",
                risk_level="low",
            ),
            "compute_statistics": ToolDefinition(
                name="compute_statistics",
                description="Compute statistics over data",
                category="compute",
                risk_level="low",
            ),
            "search_kb": ToolDefinition(
                name="search_kb",
                description="Search the support knowledge base",
                category="support",
                risk_level="low",
            ),
            "draft_reply": ToolDefinition(
                name="draft_reply",
                description="Draft a customer-facing support reply",
                category="support",
                risk_level="low",
            ),
            "escalate_ticket": ToolDefinition(
                name="escalate_ticket",
                description="Escalate a support incident",
                category="support",
                risk_level="medium",
            ),
            "update_ticket": ToolDefinition(
                name="update_ticket",
                description="Update ticket metadata",
                category="support",
                risk_level="medium",
            ),
            "update_database": ToolDefinition(
                name="update_database",
                description="Update a database record",
                category="data",
                risk_level="high",
                approval_required=True,
            ),
            "execute_shell": ToolDefinition(
                name="execute_shell",
                description="Run a shell command in a controlled environment",
                category="system",
                risk_level="critical",
                approval_required=True,
                blocked_argument_patterns=[
                    r"(?i)(^|[;\n\r\s])rm\s+-rf\b",
                    r"(?i)curl\s+.*\|\s*sh\b",
                    r"(?i)\bsudo\b",
                    r"(?i)\bmkfs\.",
                    r"(?i)\bdd\s+if=",
                ],
                allowed_argument_keys=["command", "cwd", "timeout_seconds", "human_approved"],
            ),
            "access_secrets": ToolDefinition(
                name="access_secrets",
                description="Read secrets from a managed secret store",
                category="security",
                risk_level="critical",
                approval_required=True,
            ),
        }

    def _load_tool_registry(self, registry_config: Dict[str, Any]) -> Dict[str, ToolDefinition]:
        registry: Dict[str, ToolDefinition] = {}
        for tool_name, config in registry_config.items():
            registry[tool_name] = ToolDefinition(
                name=tool_name,
                description=config.get("description", ""),
                category=config.get("category", "general"),
                risk_level=config.get("risk_level", "low"),
                approval_required=config.get("approval_required", False),
                blocked_argument_patterns=list(config.get("blocked_argument_patterns", [])),
                allowed_argument_keys=list(config.get("allowed_argument_keys", [])),
            )
        return registry
    
    def check_policy(
        self,
        agent_id: str,
        tool_name: str,
        arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Check if a tool call is allowed under the agent's policy.
        
        Returns:
            {
                "allowed": bool,
                "reason": str,
                "policy_id": str
            }
        """
        policy = self.policies.get(agent_id, self._default_policy)
        
        # Check 1: Tool allowlist
        if not self._check_tool_allowed(tool_name, policy):
            return {
                "allowed": False,
                "reason": f"Tool '{tool_name}' not in allowlist for agent '{agent_id}'",
                "policy_id": agent_id
            }
        
        # Check 2: Blocked operations
        if self._check_blocked_operation(tool_name, arguments, policy):
            return {
                "allowed": False,
                "reason": f"Tool call matches blocked operation pattern",
                "policy_id": agent_id
            }

        # Check 3: Tool registry
        tool_definition = self.tool_registry.get(tool_name)
        if tool_definition is None:
            return {
                "allowed": False,
                "reason": f"Tool '{tool_name}' is not registered in Fence's tool registry",
                "policy_id": agent_id
            }

        # Check 4: Risk / approval requirements
        approval_result = self._check_approval_requirement(tool_definition, arguments)
        if not approval_result["allowed"]:
            return {
                "allowed": False,
                "reason": approval_result["reason"],
                "policy_id": agent_id
            }

        # Check 5: Argument safety patterns
        pattern_result = self._check_argument_patterns(tool_definition, arguments)
        if not pattern_result["allowed"]:
            return {
                "allowed": False,
                "reason": pattern_result["reason"],
                "policy_id": agent_id
            }

        # Check 6: RBAC
        if not self._check_rbac(tool_name, arguments, policy):
            return {
                "allowed": False,
                "reason": f"Role-based access denied for agent '{agent_id}'",
                "policy_id": agent_id
            }
        
        # Check 7: Rate limits
        if not self._check_rate_limit(agent_id, policy):
            return {
                "allowed": False,
                "reason": f"Rate limit exceeded for agent '{agent_id}'",
                "policy_id": agent_id
            }
        
        logger.info(f"✓ Policy check passed: {agent_id} → {tool_name}")
        return {
            "allowed": True,
            "reason": "All safety checks passed",
            "policy_id": agent_id
        }
    
    def _check_tool_allowed(self, tool_name: str, policy: SafetyPolicy) -> bool:
        """Check if tool is in the allowlist"""
        if "*" in policy.allowed_tools:
            return True
        return tool_name in policy.allowed_tools
    
    def _check_blocked_operation(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        policy: SafetyPolicy
    ) -> bool:
        """
        Detect blocked operations.
        Examples:
        - Tool name matches blocked operation
        - Arguments contain dangerous patterns
        """
        # Check direct tool name match
        if "*" in policy.blocked_operations:
            return True

        if tool_name in policy.blocked_operations:
            return True
        
        # Check operation patterns in arguments
        dangerous_keys = ["password", "secret", "api_key", "token"]
        for key in dangerous_keys:
            if key in arguments:
                logger.warning(f"Dangerous argument detected: {key}")
                return True

        return False

    def _check_approval_requirement(
        self,
        tool_definition: ToolDefinition,
        arguments: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Require explicit human approval for risky tools."""
        if not tool_definition.approval_required:
            return {"allowed": True, "reason": "Approval not required"}

        human_approved = arguments.get("human_approved") is True or bool(arguments.get("approval_token"))
        if not human_approved:
            return {
                "allowed": False,
                "reason": f"Tool '{tool_definition.name}' requires human approval before execution",
            }

        return {"allowed": True, "reason": "Approval satisfied"}

    def _check_argument_patterns(
        self,
        tool_definition: ToolDefinition,
        arguments: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Block dangerous argument strings that match registry patterns."""
        if tool_definition.allowed_argument_keys:
            unexpected_keys = [
                key for key in arguments.keys()
                if key not in tool_definition.allowed_argument_keys
                and not key.startswith("_")
            ]
            if unexpected_keys:
                return {
                    "allowed": False,
                    "reason": (
                        f"Tool '{tool_definition.name}' received unexpected argument keys: "
                        f"{', '.join(sorted(unexpected_keys))}"
                    ),
                }

        if not tool_definition.blocked_argument_patterns:
            return {"allowed": True, "reason": "No blocked patterns matched"}

        for pattern in tool_definition.blocked_argument_patterns:
            regex = re.compile(pattern)
            if self._argument_payload_matches(arguments, regex):
                return {
                    "allowed": False,
                    "reason": (
                        f"Tool '{tool_definition.name}' arguments matched blocked pattern: "
                        f"{pattern}"
                    ),
                }

        return {"allowed": True, "reason": "No blocked patterns matched"}

    def _argument_payload_matches(self, value: Any, regex: re.Pattern[str]) -> bool:
        if isinstance(value, dict):
            return any(self._argument_payload_matches(v, regex) for v in value.values())
        if isinstance(value, list):
            return any(self._argument_payload_matches(item, regex) for item in value)
        if isinstance(value, str):
            return bool(regex.search(value))
        return False

    def _check_rbac(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        policy: SafetyPolicy
    ) -> bool:
        """Check whether the requested role can use the tool."""
        if not policy.rbac_roles:
            return True

        requested_role = arguments.get("role")
        if not requested_role:
            return True

        allowed_tools = policy.rbac_roles.get(requested_role, [])
        if "*" in allowed_tools:
            return True

        if tool_name not in allowed_tools:
            logger.warning(
                "RBAC blocked tool %s for role %s", tool_name, requested_role
            )
            return False

        return True
    
    def _check_rate_limit(self, agent_id: str, policy: SafetyPolicy) -> bool:
        """Check if agent exceeds rate limits"""
        limit_per_minute = policy.rate_limits.get("calls_per_minute", 60)
        
        if agent_id not in self.call_history:
            self.call_history[agent_id] = []
        
        # Clean old entries (older than 1 minute)
        now = datetime.utcnow()
        self.call_history[agent_id] = [
            ts for ts in self.call_history[agent_id]
            if now - ts < timedelta(minutes=1)
        ]
        
        # Check if over limit
        if len(self.call_history[agent_id]) >= limit_per_minute:
            return False
        
        # Record this call
        self.call_history[agent_id].append(now)
        return True
    
    def get_policy_info(self, agent_id: str) -> Dict[str, Any]:
        """Get policy details for an agent"""
        policy = self.policies.get(agent_id, self._default_policy)
        return {
            "agent_id": policy.agent_id,
            "allowed_tools": policy.allowed_tools,
            "blocked_operations": policy.blocked_operations,
            "rate_limits": policy.rate_limits,
            "rbac_roles": policy.rbac_roles,
            "approval_threshold": policy.approval_threshold
        }

    def get_tool_info(self, tool_name: str) -> Dict[str, Any]:
        """Get registry details for a tool."""
        tool = self.tool_registry.get(tool_name)
        if tool is None:
            return {"error": f"Tool '{tool_name}' is not registered"}
        return {
            "name": tool.name,
            "description": tool.description,
            "category": tool.category,
            "risk_level": tool.risk_level,
            "approval_required": tool.approval_required,
            "blocked_argument_patterns": tool.blocked_argument_patterns,
            "allowed_argument_keys": tool.allowed_argument_keys,
        }

    def list_tools(self) -> List[Dict[str, Any]]:
        """Return all registered tools."""
        return [self.get_tool_info(tool_name) for tool_name in sorted(self.tool_registry.keys())]


# Example usage
if __name__ == "__main__":
    engine = SafetyEngine()
    
    # Test: Allowed call
    result = engine.check_policy(
        agent_id="research-agent",
        tool_name="search",
        arguments={"query": "AI safety"}
    )
    print(f"Search call: {result}")
    
    # Test: Blocked call
    result = engine.check_policy(
        agent_id="research-agent",
        tool_name="execute_shell",
        arguments={"command": "rm -rf /tmp/users", "cwd": "/tmp", "timeout_seconds": 5}
    )
    print(f"Shell call: {result}")
