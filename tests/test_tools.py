"""
Unit tests for OpenClaw tools.

We test the inner async tool functions directly by extracting them from the
AgentIQ generator pattern — no LLM or network calls required for most tests.
"""

from __future__ import annotations

import asyncio
import math
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Helpers ────────────────────────────────────────────────────────────────────


async def _extract_fn(generator_coro):
    """Pull the first FunctionInfo out of an AgentIQ tool generator and return its fn."""
    items = []
    async for fn_info in generator_coro:
        items.append(fn_info)
    # FunctionInfo stores the callable in .fn
    return items[0].fn if items else None


# ── Calculator ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_calculator_basic():
    from openclaw.register import CalculatorConfig, calculator_tool

    config = CalculatorConfig()
    fn = await _extract_fn(calculator_tool(config, MagicMock()))
    assert fn is not None

    result = await fn("2 + 2")
    assert "4" in result


@pytest.mark.asyncio
async def test_calculator_sqrt():
    from openclaw.register import CalculatorConfig, calculator_tool

    fn = await _extract_fn(calculator_tool(CalculatorConfig(), MagicMock()))
    result = await fn("sqrt(16)")
    assert "4.0" in result or "4" in result


@pytest.mark.asyncio
async def test_calculator_division_by_zero():
    from openclaw.register import CalculatorConfig, calculator_tool

    fn = await _extract_fn(calculator_tool(CalculatorConfig(), MagicMock()))
    result = await fn("1 / 0")
    assert "zero" in result.lower()


@pytest.mark.asyncio
async def test_calculator_invalid_expression():
    from openclaw.register import CalculatorConfig, calculator_tool

    fn = await _extract_fn(calculator_tool(CalculatorConfig(), MagicMock()))
    result = await fn("import os; os.system('ls')")
    # Should fail safely — builtins are blocked
    assert "Cannot evaluate" in result or "Error" in result or "error" in result.lower()


@pytest.mark.asyncio
async def test_calculator_pi():
    from openclaw.register import CalculatorConfig, calculator_tool

    fn = await _extract_fn(calculator_tool(CalculatorConfig(), MagicMock()))
    result = await fn("pi")
    assert str(math.pi)[:5] in result


# ── Datetime ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_datetime_returns_utc():
    from openclaw.register import DatetimeInfoConfig, datetime_info_tool

    fn = await _extract_fn(datetime_info_tool(DatetimeInfoConfig(), MagicMock()))
    result = await fn("")
    assert "UTC" in result
    assert "2026" in result  # sanity check for year


@pytest.mark.asyncio
async def test_datetime_has_iso_format():
    from openclaw.register import DatetimeInfoConfig, datetime_info_tool

    fn = await _extract_fn(datetime_info_tool(DatetimeInfoConfig(), MagicMock()))
    result = await fn("ignored")
    assert "ISO 8601" in result
    assert "T" in result  # ISO 8601 separator


# ── System info ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_system_info_returns_os():
    from openclaw.register import SystemInfoConfig, system_info_tool

    fn = await _extract_fn(system_info_tool(SystemInfoConfig(), MagicMock()))
    result = await fn("")
    assert "System Information" in result
    assert "OS" in result
    assert "Python" in result


# ── URL fetch ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_url_fetch_rejects_non_http():
    from openclaw.register import UrlFetchConfig, url_fetch_tool

    fn = await _extract_fn(url_fetch_tool(UrlFetchConfig(), MagicMock()))
    result = await fn("ftp://example.com")
    assert "must start with http" in result


@pytest.mark.asyncio
async def test_url_fetch_success(respx_mock):
    """Test URL fetching with a mocked HTTP response."""
    pytest.importorskip("respx")
    import httpx
    import respx

    from openclaw.register import UrlFetchConfig, url_fetch_tool

    with respx.mock:
        respx.get("https://example.com/").mock(
            return_value=httpx.Response(200, text="Hello from example.com")
        )
        fn = await _extract_fn(url_fetch_tool(UrlFetchConfig(), MagicMock()))
        result = await fn("https://example.com/")
        assert "200" in result
        assert "Hello from example.com" in result


@pytest.mark.asyncio
async def test_url_fetch_http_error():
    """Test that HTTP errors are handled gracefully."""
    pytest.importorskip("respx")
    import httpx
    import respx

    from openclaw.register import UrlFetchConfig, url_fetch_tool

    with respx.mock:
        respx.get("https://example.com/notfound").mock(
            return_value=httpx.Response(404, text="Not Found")
        )
        fn = await _extract_fn(url_fetch_tool(UrlFetchConfig(), MagicMock()))
        result = await fn("https://example.com/notfound")
        assert "404" in result


# ── Web search (mocked) ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_web_search_returns_results():
    from openclaw.register import WebSearchConfig, web_search_tool

    fake_results = [
        {"title": "NVIDIA GTC", "href": "https://nvidia.com/gtc", "body": "Annual GPU tech conference."}
    ]

    with patch("duckduckgo_search.DDGS") as mock_ddgs_cls:
        mock_ddgs = MagicMock()
        mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
        mock_ddgs.__exit__ = MagicMock(return_value=False)
        mock_ddgs.text.return_value = iter(fake_results)
        mock_ddgs_cls.return_value = mock_ddgs

        fn = await _extract_fn(web_search_tool(WebSearchConfig(), MagicMock()))
        result = await fn("NVIDIA GTC")
        assert "NVIDIA GTC" in result
        assert "nvidia.com/gtc" in result


@pytest.mark.asyncio
async def test_web_search_no_results():
    from openclaw.register import WebSearchConfig, web_search_tool

    with patch("duckduckgo_search.DDGS") as mock_ddgs_cls:
        mock_ddgs = MagicMock()
        mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
        mock_ddgs.__exit__ = MagicMock(return_value=False)
        mock_ddgs.text.return_value = iter([])
        mock_ddgs_cls.return_value = mock_ddgs

        fn = await _extract_fn(web_search_tool(WebSearchConfig(), MagicMock()))
        result = await fn("xyzzy no results query 12345")
        assert "No results" in result


# ── Wikipedia (mocked) ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_wiki_search_found():
    from openclaw.register import WikiSearchConfig, wiki_search_tool

    mock_page = MagicMock()
    mock_page.exists.return_value = True
    mock_page.title = "Transformer (neural network)"
    mock_page.fullurl = "https://en.wikipedia.org/wiki/Transformer_(neural_network)"
    mock_page.summary = "The transformer is a deep learning architecture. It was introduced in 2017."

    with patch("wikipediaapi.Wikipedia") as mock_wiki_cls:
        mock_wiki_cls.return_value.page.return_value = mock_page
        fn = await _extract_fn(wiki_search_tool(WikiSearchConfig(), MagicMock()))
        result = await fn("Transformer")
        assert "Transformer" in result
        assert "wikipedia.org" in result


@pytest.mark.asyncio
async def test_wiki_search_not_found():
    from openclaw.register import WikiSearchConfig, wiki_search_tool

    mock_page = MagicMock()
    mock_page.exists.return_value = False

    with patch("wikipediaapi.Wikipedia") as mock_wiki_cls:
        mock_wiki_cls.return_value.page.return_value = mock_page
        fn = await _extract_fn(wiki_search_tool(WikiSearchConfig(), MagicMock()))
        result = await fn("xyzzy12345nonexistent")
        assert "No Wikipedia article" in result


# ── Config validation ──────────────────────────────────────────────────────────


def test_web_search_config_defaults():
    from openclaw.register import WebSearchConfig

    cfg = WebSearchConfig()
    assert cfg.max_results == 5
    assert cfg.region == "wt-wt"


def test_web_search_config_bounds():
    from openclaw.register import WebSearchConfig

    with pytest.raises(Exception):
        WebSearchConfig(max_results=0)   # ge=1
    with pytest.raises(Exception):
        WebSearchConfig(max_results=21)  # le=20


def test_url_fetch_config_defaults():
    from openclaw.register import UrlFetchConfig

    cfg = UrlFetchConfig()
    assert cfg.timeout_seconds == 15.0
    assert cfg.max_chars == 4000


def test_code_runner_disabled_by_default():
    from openclaw.register import CodeRunnerConfig

    cfg = CodeRunnerConfig()
    assert cfg.allowed is False


def test_memory_config_defaults():
    from openclaw.register import MemoryToolConfig

    cfg = MemoryToolConfig()
    assert cfg.user_id == "default"
    assert cfg.provider == "local"
