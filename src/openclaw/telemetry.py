"""
OpenClaw Telemetry
──────────────────
Sets up OpenTelemetry tracing for the AgentIQ workflow.

Supported backends (auto-detected from environment variables):

  Phoenix (Arize):
    PHOENIX_COLLECTOR_ENDPOINT=http://localhost:4317   (gRPC OTLP)
    # or just PHOENIX_COLLECTOR_ENDPOINT=http://localhost:6006  (HTTP OTLP)

  Langfuse:
    LANGFUSE_SECRET_KEY=sk-lf-...
    LANGFUSE_PUBLIC_KEY=pk-lf-...
    LANGFUSE_HOST=https://cloud.langfuse.com   (or self-hosted URL)

If neither is configured, telemetry is a no-op.

Usage (called automatically by app.py and mcp_server.py):
    from openclaw.telemetry import setup_telemetry
    setup_telemetry()
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def _setup_phoenix() -> bool:
    """Configure OTLP export to an Arize Phoenix collector. Returns True on success."""
    endpoint = os.environ.get("PHOENIX_COLLECTOR_ENDPOINT", "").rstrip("/")
    if not endpoint:
        return False

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create({"service.name": "openclaw"})
        provider = TracerProvider(resource=resource)

        # Phoenix accepts gRPC on :4317 or HTTP on /v1/traces
        if "4317" in endpoint or endpoint.startswith("grpc"):
            exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
        else:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter as HTTPExporter,
            )
            exporter = HTTPExporter(endpoint=f"{endpoint}/v1/traces")

        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)

        # Auto-instrument LangChain if available
        try:
            from opentelemetry.instrumentation.langchain import LangchainInstrumentor  # type: ignore
            LangchainInstrumentor().instrument()
        except ImportError:
            pass

        logger.info("Phoenix telemetry configured → %s", endpoint)
        return True

    except ImportError as exc:
        logger.warning(
            "Phoenix telemetry skipped (missing packages: %s). "
            "Install with: pip install 'openclaw[telemetry]'",
            exc,
        )
        return False
    except Exception as exc:
        logger.warning("Phoenix telemetry setup failed: %s", exc)
        return False


def _setup_langfuse() -> bool:
    """Configure Langfuse tracing via its OpenTelemetry SDK. Returns True on success."""
    secret_key = os.environ.get("LANGFUSE_SECRET_KEY", "")
    public_key = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
    host = os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com").rstrip("/")

    if not (secret_key and public_key):
        return False

    try:
        from langfuse.opentelemetry import LangfuseExporter  # type: ignore
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create({"service.name": "openclaw"})
        provider = TracerProvider(resource=resource)
        exporter = LangfuseExporter(
            public_key=public_key,
            secret_key=secret_key,
            host=host,
        )
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)

        # Auto-instrument LangChain if available
        try:
            from opentelemetry.instrumentation.langchain import LangchainInstrumentor  # type: ignore
            LangchainInstrumentor().instrument()
        except ImportError:
            pass

        logger.info("Langfuse telemetry configured → %s", host)
        return True

    except ImportError as exc:
        logger.warning(
            "Langfuse telemetry skipped (missing packages: %s). "
            "Install with: pip install 'openclaw[telemetry]'",
            exc,
        )
        return False
    except Exception as exc:
        logger.warning("Langfuse telemetry setup failed: %s", exc)
        return False


def setup_telemetry() -> str:
    """Initialize telemetry based on environment variables.

    Tries Phoenix first, then Langfuse. If neither backend is configured,
    this is a no-op.

    Returns:
        A string describing which backend was activated, or 'disabled'.
    """
    if _setup_phoenix():
        return "phoenix"
    if _setup_langfuse():
        return "langfuse"
    logger.debug(
        "No telemetry backend configured. "
        "Set PHOENIX_COLLECTOR_ENDPOINT or LANGFUSE_* env vars to enable tracing."
    )
    return "disabled"
