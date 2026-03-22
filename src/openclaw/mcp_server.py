"""
OpenClaw MCP Server
───────────────────
Exposes the OpenClaw AgentIQ workflow as a Model Context Protocol (MCP) server
using the stdio transport, so any MCP-compatible client (Claude Desktop, Continue,
Cursor, etc.) can use OpenClaw as an AI tool.

Install & run:
    pip install -e ".[mcp]"
    openclaw-mcp                            # default config
    openclaw-mcp --config config_local.yml  # local model

Configure in Claude Desktop (~/Library/Application Support/Claude/claude_desktop_config.json):
    {
      "mcpServers": {
        "openclaw": {
          "command": "openclaw-mcp",
          "env": { "NVIDIA_API_KEY": "nvapi-..." }
        }
      }
    }
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from openclaw.telemetry import setup_telemetry

logger = logging.getLogger(__name__)

CONFIGS_DIR = Path(__file__).parent / "configs"
DEFAULT_CONFIG = "config.yml"


def _get_mcp():
    """Import FastMCP, giving a helpful error if mcp is not installed."""
    try:
        from mcp.server.fastmcp import FastMCP  # type: ignore
        return FastMCP
    except ImportError:
        print(
            "ERROR: 'mcp' package is not installed.\n"
            "Install it with: pip install 'openclaw[mcp]'",
            file=sys.stderr,
        )
        sys.exit(1)


async def _build_server(config_path: str):
    """Create and return a configured FastMCP server instance."""
    FastMCP = _get_mcp()

    try:
        from aiq.runtime.loader import load_workflow  # type: ignore
    except ImportError:
        from nat.runtime.loader import load_workflow  # type: ignore

    mcp = FastMCP(
        "OpenClaw",
        instructions=(
            "OpenClaw is an AI agent powered by NVIDIA NIM LLMs. "
            "It has access to web search, Wikipedia, URL fetching, a calculator, "
            "datetime lookup, system info, and persistent memory. "
            "Ask it anything — it will pick the right tools automatically."
        ),
    )

    # We need a long-lived session manager. Use a module-level slot so the
    # lifecycle spans the server's lifetime.
    _sm_ref: dict = {}

    async with load_workflow(config_path, max_concurrency=-1) as session_manager:
        _sm_ref["sm"] = session_manager

        @mcp.tool()
        async def ask(message: str) -> str:
            """Ask the OpenClaw AI agent a question.

            OpenClaw can search the web, look up Wikipedia articles, fetch URLs,
            evaluate maths, recall persistent memories, and answer general questions.

            Args:
                message: Your question or instruction in plain English.

            Returns:
                The agent's answer as plain text.
            """
            sm = _sm_ref.get("sm")
            if sm is None:
                return "Agent is not ready yet."
            try:
                async with sm.session() as session:
                    async with session.run(message) as runner:
                        return await runner.result(to_type=str)
            except Exception as exc:
                logger.exception("Agent error in MCP handler")
                return f"Agent error: {exc}"

        @mcp.tool()
        async def store_memory(fact: str) -> str:
            """Store a fact in OpenClaw's persistent memory for future sessions.

            Args:
                fact: A short statement to remember, e.g. 'User is based in Berlin'.

            Returns:
                Confirmation string.
            """
            # Delegate to the agent so it uses the registered memory tool
            return await ask(f"Please store this in your memory: {fact}")

        @mcp.tool()
        async def recall_memory(query: str) -> str:
            """Search OpenClaw's persistent memory for relevant facts.

            Args:
                query: A topic or question to search memories for.

            Returns:
                Matching memories as plain text.
            """
            return await ask(f"Please search your memory for: {query}")

        # Run the MCP server (stdio transport) — this blocks until the client disconnects
        await mcp.run_async(transport="stdio")


def main() -> None:
    parser = argparse.ArgumentParser(description="OpenClaw MCP Server (stdio)")
    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG,
        help=f"Config file (relative to configs/ or absolute). Default: {DEFAULT_CONFIG}",
    )
    parser.add_argument(
        "--log-level",
        default="WARNING",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: WARNING — MCP clients read stdout so keep it quiet)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        stream=sys.stderr,  # must not pollute stdout (used for MCP messages)
    )

    setup_telemetry()

    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = CONFIGS_DIR / config_path
    if not config_path.exists():
        print(f"ERROR: Config not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    asyncio.run(_build_server(str(config_path)))


if __name__ == "__main__":
    main()
