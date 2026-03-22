"""
OpenClaw Agent — NVIDIA AgentIQ registration module.

Registers all tools and the top-level OpenClaw agent workflow.
Every component is exposed via the `aiq.components` entry point so that
AgentIQ's plugin system can discover and wire them from YAML configs.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import textwrap
from datetime import datetime, timezone
from typing import Any

import httpx
from pydantic import Field

from aiq.builder.builder import Builder
from aiq.builder.function_info import FunctionInfo
from aiq.cli.register_workflow import register_function
from aiq.data_models.function import FunctionBaseConfig

# ---------------------------------------------------------------------------
# Tool: web_search  (DuckDuckGo — no API key required)
# ---------------------------------------------------------------------------


class WebSearchConfig(FunctionBaseConfig, name="openclaw_web_search"):
    max_results: int = Field(5, ge=1, le=20, description="Maximum number of search results to return")
    region: str = Field("wt-wt", description="DuckDuckGo region code, e.g. 'us-en', 'wt-wt' for global")


@register_function(config_type=WebSearchConfig)
async def web_search_tool(config: WebSearchConfig, builder: Builder):
    """DuckDuckGo web search — no API key required."""

    async def _search(query: str) -> str:
        """Search the web using DuckDuckGo and return a formatted list of results.

        Args:
            query: The search query string.

        Returns:
            A formatted string with titles, URLs, and snippets.
        """
        try:
            from duckduckgo_search import DDGS

            results: list[dict[str, Any]] = []
            with DDGS() as ddgs:
                for r in ddgs.text(query, region=config.region, max_results=config.max_results):
                    results.append(r)

            if not results:
                return f"No results found for: {query}"

            lines = [f"Search results for: {query!r}\n"]
            for i, r in enumerate(results, 1):
                lines.append(f"{i}. {r.get('title', 'No title')}")
                lines.append(f"   URL: {r.get('href', '')}")
                lines.append(f"   {r.get('body', '')}\n")
            return "\n".join(lines)

        except ImportError:
            return "duckduckgo-search is not installed. Run: pip install duckduckgo-search"
        except Exception as exc:  # noqa: BLE001
            return f"Search failed: {exc}"

    yield FunctionInfo.from_fn(_search, description="Search the web with DuckDuckGo")


# ---------------------------------------------------------------------------
# Tool: wikipedia_search
# ---------------------------------------------------------------------------


class WikiSearchConfig(FunctionBaseConfig, name="openclaw_wiki_search"):
    language: str = Field("en", description="Wikipedia language code, e.g. 'en', 'es', 'fr'")
    sentences: int = Field(5, ge=1, le=20, description="Number of summary sentences to return")


@register_function(config_type=WikiSearchConfig)
async def wiki_search_tool(config: WikiSearchConfig, builder: Builder):
    """Wikipedia article summary lookup."""

    async def _wiki(topic: str) -> str:
        """Look up a topic on Wikipedia and return a concise summary.

        Args:
            topic: The topic or article title to look up.

        Returns:
            A plain-text summary of the Wikipedia article.
        """
        try:
            import wikipediaapi  # type: ignore

            wiki = wikipediaapi.Wikipedia(
                language=config.language,
                user_agent="OpenClaw-Bot/0.1 (https://github.com/jacattac314/The-Orquestrator-)",
            )
            page = wiki.page(topic)
            if not page.exists():
                return f"No Wikipedia article found for: {topic!r}"

            summary = page.summary
            # Trim to requested sentence count
            import re
            sentences = re.split(r"(?<=[.!?])\s+", summary.strip())
            trimmed = " ".join(sentences[: config.sentences])
            return f"Wikipedia — {page.title}\nURL: {page.fullurl}\n\n{trimmed}"

        except ImportError:
            return "wikipedia-api is not installed. Run: pip install wikipedia-api"
        except Exception as exc:  # noqa: BLE001
            return f"Wikipedia lookup failed: {exc}"

    yield FunctionInfo.from_fn(_wiki, description="Fetch a Wikipedia article summary for a topic")


# ---------------------------------------------------------------------------
# Tool: datetime_info
# ---------------------------------------------------------------------------


class DatetimeInfoConfig(FunctionBaseConfig, name="openclaw_datetime"):
    timezone_name: str = Field("UTC", description="Timezone name, e.g. 'UTC', 'US/Eastern'")


@register_function(config_type=DatetimeInfoConfig)
async def datetime_info_tool(config: DatetimeInfoConfig, builder: Builder):
    """Returns the current date and time."""

    async def _get_datetime(_: str = "") -> str:
        """Return the current date and time.

        Args:
            _: Ignored input (pass any string or leave empty).

        Returns:
            Current date and time as a formatted string.
        """
        now = datetime.now(tz=timezone.utc)
        return (
            f"Current UTC datetime: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}\n"
            f"ISO 8601: {now.isoformat()}\n"
            f"Unix timestamp: {int(now.timestamp())}"
        )

    yield FunctionInfo.from_fn(_get_datetime, description="Get the current date and time in UTC")


# ---------------------------------------------------------------------------
# Tool: system_info
# ---------------------------------------------------------------------------


class SystemInfoConfig(FunctionBaseConfig, name="openclaw_system_info"):
    pass  # no config fields needed


@register_function(config_type=SystemInfoConfig)
async def system_info_tool(config: SystemInfoConfig, builder: Builder):
    """Returns basic information about the host system."""

    async def _get_system_info(_: str = "") -> str:
        """Return information about the host system (OS, Python version, hardware).

        Args:
            _: Ignored input.

        Returns:
            A formatted string with system information.
        """
        info = {
            "OS": platform.system(),
            "OS version": platform.version(),
            "Architecture": platform.machine(),
            "Processor": platform.processor() or "unknown",
            "Python version": platform.python_version(),
            "Hostname": platform.node(),
        }

        # Try to detect NVIDIA GPU
        try:
            gpu_output = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                stderr=subprocess.DEVNULL,
                timeout=5,
                text=True,
            ).strip()
            info["NVIDIA GPU(s)"] = gpu_output or "none detected"
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            info["NVIDIA GPU(s)"] = "nvidia-smi not available"

        lines = ["System Information:"]
        for k, v in info.items():
            lines.append(f"  {k}: {v}")
        return "\n".join(lines)

    yield FunctionInfo.from_fn(_get_system_info, description="Get information about the host system and hardware")


# ---------------------------------------------------------------------------
# Tool: url_fetch  (retrieve content from a URL)
# ---------------------------------------------------------------------------


class UrlFetchConfig(FunctionBaseConfig, name="openclaw_url_fetch"):
    timeout_seconds: float = Field(15.0, ge=1.0, description="HTTP request timeout in seconds")
    max_chars: int = Field(4000, ge=100, description="Maximum characters to return from the response body")


@register_function(config_type=UrlFetchConfig)
async def url_fetch_tool(config: UrlFetchConfig, builder: Builder):
    """Fetches the text content of a URL."""

    async def _fetch(url: str) -> str:
        """Fetch the text content from a given URL.

        Args:
            url: The full URL to fetch (must start with http:// or https://).

        Returns:
            The text body of the response, truncated to max_chars.
        """
        if not url.startswith(("http://", "https://")):
            return "Error: URL must start with http:// or https://"

        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=config.timeout_seconds) as client:
                response = await client.get(
                    url,
                    headers={"User-Agent": "OpenClaw-Bot/0.1"},
                )
                response.raise_for_status()
                text = response.text[: config.max_chars]
                return f"URL: {url}\nStatus: {response.status_code}\n\n{text}"
        except httpx.HTTPStatusError as exc:
            return f"HTTP error {exc.response.status_code} fetching {url}"
        except Exception as exc:  # noqa: BLE001
            return f"Failed to fetch {url}: {exc}"

    yield FunctionInfo.from_fn(_fetch, description="Fetch the text content of any HTTP/HTTPS URL")


# ---------------------------------------------------------------------------
# Tool: code_runner  (safe Python snippet execution in a subprocess)
# ---------------------------------------------------------------------------


class CodeRunnerConfig(FunctionBaseConfig, name="openclaw_code_runner"):
    timeout_seconds: int = Field(10, ge=1, le=60, description="Maximum seconds allowed for code execution")
    allowed: bool = Field(
        False,
        description="Must be set to true to enable code execution (disabled by default for safety)",
    )


@register_function(config_type=CodeRunnerConfig)
async def code_runner_tool(config: CodeRunnerConfig, builder: Builder):
    """Executes a Python code snippet in an isolated subprocess."""

    async def _run_code(code: str) -> str:
        """Execute a Python code snippet and return stdout/stderr.

        WARNING: Only enable this tool if you trust the agent's outputs.
        Set `allowed: true` in the config to activate.

        Args:
            code: The Python source code to execute.

        Returns:
            Combined stdout and stderr from the execution.
        """
        if not config.allowed:
            return (
                "Code execution is disabled. "
                "Set `allowed: true` in the openclaw_code_runner config to enable it."
            )
        try:
            result = subprocess.run(
                ["python3", "-c", code],
                capture_output=True,
                text=True,
                timeout=config.timeout_seconds,
            )
            output_parts = []
            if result.stdout:
                output_parts.append(f"stdout:\n{result.stdout.rstrip()}")
            if result.stderr:
                output_parts.append(f"stderr:\n{result.stderr.rstrip()}")
            if not output_parts:
                output_parts.append("(no output)")
            return "\n".join(output_parts)
        except subprocess.TimeoutExpired:
            return f"Execution timed out after {config.timeout_seconds}s"
        except Exception as exc:  # noqa: BLE001
            return f"Execution failed: {exc}"

    yield FunctionInfo.from_fn(_run_code, description="Execute a Python code snippet and return its output")


# ---------------------------------------------------------------------------
# Tool: calculator  (safe arithmetic evaluation)
# ---------------------------------------------------------------------------


class CalculatorConfig(FunctionBaseConfig, name="openclaw_calculator"):
    pass


@register_function(config_type=CalculatorConfig)
async def calculator_tool(config: CalculatorConfig, builder: Builder):
    """Safe arithmetic calculator using Python's math module."""

    async def _calculate(expression: str) -> str:
        """Evaluate a mathematical expression and return the result.

        Supports standard arithmetic, math functions (sin, cos, sqrt, log, etc.),
        and constants (pi, e).

        Args:
            expression: A mathematical expression string, e.g. 'sqrt(2) * pi'.

        Returns:
            The numeric result as a string.
        """
        import math

        safe_globals: dict[str, Any] = {
            "__builtins__": {},
            **{name: getattr(math, name) for name in dir(math) if not name.startswith("_")},
            "abs": abs,
            "round": round,
            "int": int,
            "float": float,
        }
        try:
            result = eval(expression, safe_globals)  # noqa: S307 — intentionally restricted
            return f"{expression} = {result}"
        except ZeroDivisionError:
            return "Error: division by zero"
        except Exception as exc:  # noqa: BLE001
            return f"Cannot evaluate {expression!r}: {exc}"

    yield FunctionInfo.from_fn(_calculate, description="Evaluate a mathematical expression safely")


# ---------------------------------------------------------------------------
# Gmail email-tracking tools
# ---------------------------------------------------------------------------


class GmailListConfig(FunctionBaseConfig, name="openclaw_gmail_list"):
    max_results: int = Field(10, ge=1, le=50, description="Maximum number of messages to return")
    unread_only: bool = Field(True, description="Return only unread messages when True")


@register_function(config_type=GmailListConfig)
async def gmail_list_tool(config: GmailListConfig, builder: Builder):
    """List recent Gmail inbox messages."""

    async def _list(_: str = "") -> str:
        """List recent inbox emails.

        Args:
            _: Ignored (pass any string or leave empty).

        Returns:
            A formatted list of recent inbox messages with IDs, senders, subjects, and snippets.
        """
        from openclaw.tools.gmail_tool import list_inbox_emails
        return list_inbox_emails(max_results=config.max_results, unread_only=config.unread_only)

    yield FunctionInfo.from_fn(_list, description="List recent Gmail inbox messages (unread by default)")


class GmailReadConfig(FunctionBaseConfig, name="openclaw_gmail_read"):
    pass


@register_function(config_type=GmailReadConfig)
async def gmail_read_tool(config: GmailReadConfig, builder: Builder):
    """Read the full content of a Gmail message by ID."""

    async def _read(message_id: str) -> str:
        """Read the full content of a Gmail email.

        Args:
            message_id: The Gmail message ID (obtain from gmail_list or gmail_search).

        Returns:
            Full email headers and body text.
        """
        from openclaw.tools.gmail_tool import read_email
        return read_email(message_id)

    yield FunctionInfo.from_fn(_read, description="Read a Gmail email by its message ID")


class GmailSearchConfig(FunctionBaseConfig, name="openclaw_gmail_search"):
    max_results: int = Field(10, ge=1, le=50, description="Maximum number of results")


@register_function(config_type=GmailSearchConfig)
async def gmail_search_tool(config: GmailSearchConfig, builder: Builder):
    """Search Gmail using Gmail search operators."""

    async def _search(query: str) -> str:
        """Search Gmail for messages matching a query.

        Supports all Gmail search operators such as from:, to:, subject:,
        has:attachment, is:unread, after:, before:, etc.

        Args:
            query: Gmail search query string, e.g. 'from:boss subject:budget is:unread'.

        Returns:
            Formatted list of matching messages with IDs, senders, subjects, and snippets.
        """
        from openclaw.tools.gmail_tool import search_emails
        return search_emails(query, max_results=config.max_results)

    yield FunctionInfo.from_fn(_search, description="Search Gmail with any Gmail search operator")


class GmailFollowupConfig(FunctionBaseConfig, name="openclaw_gmail_followup"):
    days_threshold: int = Field(
        3, ge=1, le=30,
        description="Flag sent emails with no reply after this many days"
    )


@register_function(config_type=GmailFollowupConfig)
async def gmail_followup_tool(config: GmailFollowupConfig, builder: Builder):
    """Find sent emails that have received no reply after N days."""

    async def _check(_: str = "") -> str:
        """Check for sent emails that have received no reply and may need follow-up.

        Args:
            _: Ignored (pass any string or leave empty).

        Returns:
            List of unreplied sent emails older than the configured threshold, sorted by age.
        """
        from openclaw.tools.gmail_tool import check_followups
        return check_followups(days_threshold=config.days_threshold)

    yield FunctionInfo.from_fn(_check, description=f"Find sent emails with no reply after {config.days_threshold} days")


class GmailMarkConfig(FunctionBaseConfig, name="openclaw_gmail_mark"):
    pass


@register_function(config_type=GmailMarkConfig)
async def gmail_mark_tool(config: GmailMarkConfig, builder: Builder):
    """Star a Gmail message to mark it for follow-up."""

    async def _mark(message_id: str) -> str:
        """Star a Gmail email to flag it for follow-up.

        Args:
            message_id: The Gmail message ID to star.

        Returns:
            Confirmation that the email was starred.
        """
        from openclaw.tools.gmail_tool import mark_as_followup
        return mark_as_followup(message_id)

    yield FunctionInfo.from_fn(_mark, description="Star a Gmail message to mark it for follow-up")


class GmailSummaryConfig(FunctionBaseConfig, name="openclaw_gmail_summary"):
    max_unread: int = Field(20, ge=1, le=50, description="How many unread messages to include in the briefing")


@register_function(config_type=GmailSummaryConfig)
async def gmail_summary_tool(config: GmailSummaryConfig, builder: Builder):
    """Get a personal-assistant inbox briefing from Gmail."""

    async def _summary(_: str = "") -> str:
        """Get a concise personal-assistant-style inbox briefing.

        Includes unread count, recent senders, starred items, and follow-up alerts.

        Args:
            _: Ignored (pass any string or leave empty).

        Returns:
            A formatted inbox briefing with unread count, recent messages,
            starred emails, and a follow-up pending count.
        """
        from openclaw.tools.gmail_tool import get_email_summary
        return get_email_summary(max_unread=config.max_unread)

    yield FunctionInfo.from_fn(_summary, description="Get a personal-assistant inbox briefing from Gmail")


# ---------------------------------------------------------------------------
# Tool: memory  (mem0ai — persistent cross-session facts)
# ---------------------------------------------------------------------------


class MemoryToolConfig(FunctionBaseConfig, name="openclaw_memory"):
    user_id: str = Field("default", description="Identifier scoping the memory namespace")
    provider: str = Field(
        "local",
        description="'local' (on-disk via mem0) or 'cloud' (mem0 SaaS, requires MEM0_API_KEY)",
    )
    nim_base_url: str = Field(
        "https://integrate.api.nvidia.com/v1",
        description="Base URL for the NIM-compatible LLM used by mem0 local mode",
    )
    nim_model: str = Field(
        "meta/llama-3.3-70b-instruct",
        description="Model name for the NIM LLM used internally by mem0",
    )
    embedder_model: str = Field(
        "nvidia/nv-embedqa-e5-v5",
        description="Embedding model served by the same NIM endpoint",
    )


@register_function(config_type=MemoryToolConfig)
async def memory_tool(config: MemoryToolConfig, builder: Builder):
    """Persistent memory store backed by mem0ai.

    Provides two operations: store a fact and recall relevant memories.
    """

    def _make_memory():
        try:
            if config.provider == "cloud":
                from mem0 import MemoryClient  # type: ignore

                api_key = os.environ.get("MEM0_API_KEY", "")
                if not api_key:
                    return None, "MEM0_API_KEY environment variable is not set"
                return MemoryClient(api_key=api_key), None
            else:
                from mem0 import Memory  # type: ignore

                nim_api_key = os.environ.get("NVIDIA_API_KEY", "")
                mem_config = {
                    "llm": {
                        "provider": "openai",
                        "config": {
                            "model": config.nim_model,
                            "api_key": nim_api_key,
                            "openai_base_url": config.nim_base_url,
                        },
                    },
                    "embedder": {
                        "provider": "openai",
                        "config": {
                            "model": config.embedder_model,
                            "api_key": nim_api_key,
                            "openai_base_url": config.nim_base_url,
                        },
                    },
                }
                return Memory.from_config(mem_config), None
        except ImportError:
            return None, "mem0ai is not installed. Run: pip install mem0ai"
        except Exception as exc:  # noqa: BLE001
            return None, f"mem0 init failed: {exc}"

    _mem, _mem_error = _make_memory()

    async def _store(fact: str) -> str:
        """Store a fact or piece of information in persistent memory.

        Use this to remember important things the user tells you across sessions.

        Args:
            fact: A short statement or fact to remember, e.g. 'User prefers metric units'.

        Returns:
            Confirmation that the memory was stored.
        """
        if _mem is None:
            return f"Memory unavailable: {_mem_error}"
        try:
            _mem.add(fact, user_id=config.user_id)
            return f"Stored: {fact!r}"
        except Exception as exc:  # noqa: BLE001
            return f"Failed to store memory: {exc}"

    async def _recall(query: str) -> str:
        """Search persistent memory for facts relevant to the query.

        Call this at the start of a conversation to recall what you know about the user.

        Args:
            query: A natural-language question or topic to search for.

        Returns:
            Relevant memories as a formatted list, or a message if none found.
        """
        if _mem is None:
            return f"Memory unavailable: {_mem_error}"
        try:
            results = _mem.search(query, user_id=config.user_id)
            if not results:
                return "No relevant memories found."
            # mem0 returns list of dicts with 'memory' key
            lines = ["Relevant memories:"]
            for i, r in enumerate(results, 1):
                text = r.get("memory", r) if isinstance(r, dict) else str(r)
                lines.append(f"  {i}. {text}")
            return "\n".join(lines)
        except Exception as exc:  # noqa: BLE001
            return f"Failed to search memory: {exc}"

    yield FunctionInfo.from_fn(_store, description="Store a fact in persistent memory for future sessions")
    yield FunctionInfo.from_fn(_recall, description="Search persistent memory for facts relevant to a query")
