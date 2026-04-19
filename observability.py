"""
OpenTelemetry Observability Setup
Enables full-trace debugging of reasoning-to-action loops in LLM agents.

Features:
- Distributed tracing across proxy layers
- Real-time debugging capabilities
- Export to Jaeger, Datadog, or OTLP endpoints
- Automatic span creation for all key operations
"""

import os
import logging
from typing import Optional
from contextlib import contextmanager

from opentelemetry import trace, metrics

logger = logging.getLogger(__name__)


class TelemetryConfig:
    """Configuration for OpenTelemetry"""
    
    def __init__(self):
        self.service_name = os.getenv("SERVICE_NAME", "mcp-proxy")
        self.jaeger_host = os.getenv("JAEGER_HOST", "localhost")
        self.jaeger_port = int(os.getenv("JAEGER_PORT", "6831"))
        self.otlp_endpoint = os.getenv("OTLP_ENDPOINT", "http://localhost:4317")
        self.exporter_type = os.getenv("EXPORTER_TYPE", "jaeger")  # jaeger, otlp, console
        self.enabled = os.getenv("ENABLE_TELEMETRY", "true").lower() == "true"


_tracer: Optional[trace.Tracer] = None
_config = TelemetryConfig()


def setup_telemetry(
    service_name: str = "mcp-proxy",
    exporter_type: str = "jaeger"
) -> None:
    """
    Initialize OpenTelemetry with the specified exporter.
    
    Args:
        service_name: Service name for traces
        exporter_type: 'jaeger', 'otlp', or 'console'
    """
    global _tracer
    
    if not _config.enabled:
        logger.info("Telemetry disabled")
        return
    
    try:
        from opentelemetry.exporter.jaeger.thrift import JaegerExporter
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        try:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
            from opentelemetry.instrumentation.requests import RequestsInstrumentor
            from opentelemetry.instrumentation.httpx import HttpxInstrumentor
        except ModuleNotFoundError as instrumentation_error:
            logger.warning(
                "OpenTelemetry instrumentation extras are unavailable: %s. "
                "Continuing without automatic framework instrumentation.",
                instrumentation_error,
            )
            FastAPIInstrumentor = None
            RequestsInstrumentor = None
            HttpxInstrumentor = None

        # Create resource
        resource = Resource.create({
            "service.name": service_name,
            "service.version": "1.0.0",
            "environment": os.getenv("ENV", "development")
        })
        
        # Create tracer provider
        tracer_provider = TracerProvider(resource=resource)
        
        # Configure exporter based on type
        if exporter_type == "jaeger":
            _setup_jaeger_exporter(tracer_provider)
        elif exporter_type == "otlp":
            _setup_otlp_exporter(tracer_provider)
        else:
            logger.warning(f"Unknown exporter type: {exporter_type}, using console")
        
        # Set global tracer provider
        trace.set_tracer_provider(tracer_provider)
        
        # Instrument FastAPI automatically
        if FastAPIInstrumentor is not None:
            FastAPIInstrumentor().instrument()
        if RequestsInstrumentor is not None:
            RequestsInstrumentor().instrument()
        if HttpxInstrumentor is not None:
            HttpxInstrumentor().instrument()
        
        _tracer = tracer_provider.get_tracer(__name__)
        logger.info(f"✓ Telemetry initialized with {exporter_type} exporter")
        
    except Exception as e:
        logger.error(f"Failed to setup telemetry: {str(e)}")
        _tracer = trace.get_tracer(__name__)  # Fallback to no-op tracer


def _setup_jaeger_exporter(tracer_provider: "TracerProvider") -> None:
    """Setup Jaeger as the trace exporter"""
    from opentelemetry.exporter.jaeger.thrift import JaegerExporter
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    jaeger_exporter = JaegerExporter(
        agent_host_name=_config.jaeger_host,
        agent_port=_config.jaeger_port,
    )
    tracer_provider.add_span_processor(
        BatchSpanProcessor(jaeger_exporter)
    )
    logger.info(f"Jaeger exporter configured: {_config.jaeger_host}:{_config.jaeger_port}")


def _setup_otlp_exporter(tracer_provider: "TracerProvider") -> None:
    """Setup OTLP (gRPC) as the trace exporter"""
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    otlp_exporter = OTLPSpanExporter(endpoint=_config.otlp_endpoint)
    tracer_provider.add_span_processor(
        BatchSpanProcessor(otlp_exporter)
    )
    logger.info(f"OTLP exporter configured: {_config.otlp_endpoint}")


def get_tracer(name: str) -> trace.Tracer:
    """Get a tracer instance"""
    if _tracer is None:
        return trace.get_tracer(name)
    return trace.get_tracer(name)


class TracingSpan:
    """Context manager for creating spans"""
    
    def __init__(self, tracer: trace.Tracer, name: str, attributes: dict = None):
        self.tracer = tracer
        self.name = name
        self.attributes = attributes or {}
        self.span = None
    
    def __enter__(self):
        self.span = self.tracer.start_span(self.name)
        for key, value in self.attributes.items():
            self.span.set_attribute(key, value)
        return self.span
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.span.record_exception(exc_val)
        self.span.end()


# Trace decorators for easy instrumentation
def trace_span(name: str = None, attributes: dict = None):
    """Decorator to automatically create spans around functions"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            tracer = get_tracer(__name__)
            span_name = name or func.__name__
            
            with tracer.start_as_current_span(span_name) as span:
                if attributes:
                    for key, value in attributes.items():
                        span.set_attribute(key, value)
                
                try:
                    result = func(*args, **kwargs)
                    span.set_attribute("status", "success")
                    return result
                except Exception as e:
                    span.set_attribute("status", "error")
                    span.record_exception(e)
                    raise
        
        return wrapper
    return decorator


# Example trace structure
TRACE_STRUCTURE = """
Example trace for a proxy_tool_call:

Trace ID: abc123
├── proxy_tool_call (123ms)
│   ├── session_lookup (2ms)
│   │   └── Attributes: agent_id, session_id
│   ├── safety_guardrails (5ms)
│   │   ├── Attributes: allowed, policy_matched
│   │   └── Events: policy_check_started, policy_check_completed
│   ├── semantic_validation (1ms)
│   │   ├── Attributes: is_valid, errors (if any)
│   │   └── Events: schema_check_started
│   ├── budget_check (1ms)
│   │   └── Attributes: allowed, tokens_used, cost_used
│   ├── tool_execution (85ms)
│   │   ├── Attributes: tool_name, status
│   │   └── Child spans: api_call_to_external_service (70ms)
│   ├── budget_update (1ms)
│   │   └── Attributes: tokens_recorded, cost_recorded
│   └── response_assembly (28ms)

Viewing in Jaeger UI:
1. Go to http://localhost:16686
2. Select "mcp-proxy" service
3. Click on trace to see full breakdown
4. Click on spans to see attributes, events, logs
"""


# Metrics helper (for cost/token tracking)
class MetricsCollector:
    """Collect metrics for tokens and costs"""
    
    def __init__(self):
        self.meters = {}
    
    def get_meter(self, name: str):
        """Get or create a meter"""
        if name not in self.meters:
            meter_provider = metrics.get_meter_provider()
            self.meters[name] = meter_provider.get_meter(name)
        return self.meters[name]
    
    def record_tokens(self, agent_id: str, tokens: int):
        """Record token usage"""
        meter = self.get_meter("mcp-proxy")
        counter = meter.create_counter(
            "tokens_used",
            description="Total tokens used",
            unit="1"
        )
        counter.add(tokens, {"agent_id": agent_id})
    
    def record_cost(self, agent_id: str, cost: float):
        """Record API cost"""
        meter = self.get_meter("mcp-proxy")
        counter = meter.create_counter(
            "cost_usd",
            description="Total cost in USD",
            unit="1"
        )
        counter.add(cost, {"agent_id": agent_id})


# Singleton metrics collector
_metrics = MetricsCollector()


def get_metrics_collector() -> MetricsCollector:
    """Get the global metrics collector"""
    return _metrics


# Example usage
if __name__ == "__main__":
    setup_telemetry(exporter_type="jaeger")
    tracer = get_tracer(__name__)
    
    # Create a sample trace
    with tracer.start_as_current_span("example_operation") as span:
        span.set_attribute("user_id", "user_123")
        
        with tracer.start_as_current_span("sub_operation") as child_span:
            child_span.set_attribute("operation_type", "validation")
            print("Executing sub-operation...")
    
    print("\\n" + TRACE_STRUCTURE)
    print("\\nTrace exported! View it in Jaeger UI at http://localhost:16686")
