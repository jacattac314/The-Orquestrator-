"""Smoke tests for the Gradio app and telemetry module."""

from __future__ import annotations

import os


def test_app_imports():
    """Verify app.py is importable and exposes main()."""
    import openclaw.app as app

    assert callable(app.main)
    assert callable(app.respond)
    assert callable(app.clear_chat)


def test_telemetry_disabled_without_env(monkeypatch):
    """setup_telemetry() returns 'disabled' when no env vars are set."""
    monkeypatch.delenv("PHOENIX_COLLECTOR_ENDPOINT", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)

    from openclaw.telemetry import setup_telemetry

    result = setup_telemetry()
    # Should be 'disabled' (or 'phoenix'/'langfuse' if packages happen to be
    # installed and configured, but without env vars it must be 'disabled')
    assert result == "disabled"


def test_mcp_server_imports():
    """Verify mcp_server.py is importable and exposes main()."""
    import openclaw.mcp_server as mcp

    assert callable(mcp.main)


def test_register_module_imports():
    """All tool config classes and registration functions are importable."""
    from openclaw.register import (
        CalculatorConfig,
        CodeRunnerConfig,
        DatetimeInfoConfig,
        MemoryToolConfig,
        SystemInfoConfig,
        UrlFetchConfig,
        WebSearchConfig,
        WikiSearchConfig,
    )

    for cls in [
        CalculatorConfig,
        CodeRunnerConfig,
        DatetimeInfoConfig,
        MemoryToolConfig,
        SystemInfoConfig,
        UrlFetchConfig,
        WebSearchConfig,
        WikiSearchConfig,
    ]:
        instance = cls()
        assert instance is not None


def test_config_yml_exists():
    """The default config.yml is present."""
    from pathlib import Path

    config = Path(__file__).parent.parent / "src" / "openclaw" / "configs" / "config.yml"
    assert config.exists(), f"config.yml not found at {config}"


def test_config_local_yml_exists():
    """The local model config is present."""
    from pathlib import Path

    config = Path(__file__).parent.parent / "src" / "openclaw" / "configs" / "config_local.yml"
    assert config.exists(), f"config_local.yml not found at {config}"
