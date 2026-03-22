"""Shared pytest fixtures for OpenClaw tests."""

from __future__ import annotations

import pytest


@pytest.fixture
def nim_api_key(monkeypatch):
    """Provide a dummy NVIDIA API key so tools don't error on missing env var."""
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test-dummy-key")
    return "nvapi-test-dummy-key"
