"""
OpenClaw Gradio Web UI
─────────────────────
Embeds the AgentIQ workflow directly (same process, no separate server).

Run:
    python -m openclaw.app                            # default config (NIM)
    python -m openclaw.app --config config_local.yml  # local model
    openclaw-ui                                       # via installed script
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Generator

import gradio as gr

logger = logging.getLogger(__name__)

CONFIGS_DIR = Path(__file__).parent / "configs"
DEFAULT_CONFIG = "config.yml"

# ── Async runtime ────────────────────────────────────────────────────────────
# Gradio runs sync handlers in threads; we keep a dedicated event loop alive
# on a background thread so async AgentIQ context managers stay alive for the
# full app lifetime.

_loop: asyncio.AbstractEventLoop | None = None
_session_manager = None  # nat.runtime.session.SessionManager
_workflow_ctx = None     # async context manager returned by load_workflow
_ready = threading.Event()
_init_error: str | None = None


def _run_event_loop() -> None:
    """Target for the background thread that owns the async event loop."""
    global _loop
    _loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_loop)
    _loop.run_forever()


def _run_coroutine(coro):
    """Submit a coroutine to the background loop and wait for the result."""
    assert _loop is not None, "Event loop not started"
    future = asyncio.run_coroutine_threadsafe(coro, _loop)
    return future.result()


async def _startup(config_file: str) -> None:
    global _session_manager, _workflow_ctx, _init_error
    try:
        # Support both aiq.* (v1.1) and nat.* (v1.5+) namespaces
        try:
            from aiq.runtime.loader import load_workflow  # type: ignore
        except ImportError:
            from nat.runtime.loader import load_workflow  # type: ignore

        _workflow_ctx = load_workflow(config_file, max_concurrency=-1)
        _session_manager = await _workflow_ctx.__aenter__()
        logger.info("AgentIQ workflow loaded from %s", config_file)
    except Exception as exc:
        _init_error = f"Failed to load workflow: {exc}"
        logger.exception("Workflow startup failed")
    finally:
        _ready.set()


async def _shutdown() -> None:
    if _workflow_ctx is not None:
        try:
            await _workflow_ctx.__aexit__(None, None, None)
        except Exception:
            pass


async def _ask(message: str) -> str:
    """Run a single turn against the loaded workflow."""
    if _session_manager is None:
        return "⚠️  Agent not loaded. Check the terminal for errors."
    try:
        async with _session_manager.session() as session:
            async with session.run(message) as runner:
                return await runner.result(to_type=str)
    except Exception as exc:
        logger.exception("Agent error")
        return f"❌ Agent error: {exc}"


# ── Gradio helpers ────────────────────────────────────────────────────────────

def _sync_ask(message: str) -> str:
    return _run_coroutine(_ask(message))


def respond(
    message: str,
    history: list[dict],
) -> Generator[list[dict], None, None]:
    """Gradio streaming handler — yields incremental chat history."""
    if not message.strip():
        yield history
        return

    # Append the user message immediately
    history = history + [{"role": "user", "content": message}]
    yield history

    # Run the agent (blocking call on the background loop)
    bot_reply = _sync_ask(message)

    history = history + [{"role": "assistant", "content": bot_reply}]
    yield history


def clear_chat() -> list:
    return []


# ── UI construction ───────────────────────────────────────────────────────────

def build_ui(config_path: str) -> gr.Blocks:
    config_name = Path(config_path).name

    css = """
    #header { text-align: center; margin-bottom: 8px; }
    #chatbox { height: 520px; overflow-y: auto; }
    .tag { font-size: 0.78rem; color: #888; }
    """

    with gr.Blocks(
        title="OpenClaw",
        theme=gr.themes.Soft(primary_hue="green", neutral_hue="slate"),
        css=css,
    ) as demo:
        # ── Header ──
        gr.HTML(
            """
            <div id="header">
              <h1 style="margin:0;font-size:2rem;">🦾 OpenClaw</h1>
              <p style="margin:4px 0 0;color:#6b7280;">
                AI Agent &nbsp;·&nbsp; NVIDIA AgentIQ / NeMo Agent Toolkit
              </p>
            </div>
            """
        )

        # ── Status banner ──
        if _init_error:
            gr.HTML(
                f'<div style="background:#fee2e2;color:#991b1b;padding:10px 16px;'
                f'border-radius:8px;margin-bottom:8px;">'
                f'⚠️ {_init_error}</div>'
            )
        else:
            gr.HTML(
                f'<div style="background:#dcfce7;color:#166534;padding:8px 16px;'
                f'border-radius:8px;margin-bottom:8px;font-size:.875rem;">'
                f'✅ Agent ready &nbsp;·&nbsp; config: <code>{config_name}</code></div>'
            )

        # ── Chat ──
        chatbot = gr.Chatbot(
            elem_id="chatbox",
            type="messages",
            show_copy_button=True,
            avatar_images=(None, "https://developer.nvidia.com/favicon.ico"),
            label="",
        )

        with gr.Row():
            msg_box = gr.Textbox(
                placeholder="Ask OpenClaw anything…",
                show_label=False,
                scale=9,
                lines=1,
                autofocus=True,
            )
            send_btn = gr.Button("Send", variant="primary", scale=1)

        with gr.Row():
            clear_btn = gr.Button("🗑 Clear chat", size="sm", variant="secondary")
            gr.HTML(
                '<span class="tag" style="line-height:2.2;">'
                "OpenClaw uses NVIDIA NIM LLMs via AgentIQ</span>"
            )

        # ── Example prompts ──
        gr.Examples(
            examples=[
                "What are the latest NVIDIA announcements?",
                "Search Wikipedia for 'transformer neural network' and summarise it.",
                "What is the current UTC time?",
                "Calculate sqrt(2) * pi^2",
                "Fetch https://api.github.com/repos/NVIDIA/NeMo-Agent-Toolkit and summarise it.",
                "What GPU is available on this machine?",
            ],
            inputs=msg_box,
            label="Example prompts",
        )

        # ── Event wiring ──
        submit_args = dict(fn=respond, inputs=[msg_box, chatbot], outputs=chatbot)

        msg_box.submit(**submit_args).then(
            fn=lambda: gr.Textbox(value=""), outputs=msg_box
        )
        send_btn.click(**submit_args).then(
            fn=lambda: gr.Textbox(value=""), outputs=msg_box
        )
        clear_btn.click(fn=clear_chat, outputs=chatbot)

    return demo


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="OpenClaw Gradio Web UI")
    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG,
        help="Config filename (relative to configs/) or an absolute path. "
             f"Default: {DEFAULT_CONFIG}",
    )
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=7860, help="Bind port (default: 7860)")
    parser.add_argument("--share", action="store_true", help="Create a public Gradio link")
    args = parser.parse_args()

    # Resolve config path
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = CONFIGS_DIR / config_path
    if not config_path.exists():
        print(f"ERROR: Config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(name)s — %(message)s",
    )

    # Start the background event loop
    thread = threading.Thread(target=_run_event_loop, daemon=True)
    thread.start()
    # Give the loop a moment to start
    while _loop is None:
        pass

    # Bootstrap the AgentIQ workflow on the background loop
    print(f"⏳  Loading AgentIQ workflow from {config_path} …")
    asyncio.run_coroutine_threadsafe(_startup(str(config_path)), _loop)
    _ready.wait(timeout=120)

    if _init_error:
        print(f"\n⚠️  WARNING: {_init_error}")
        print("The UI will still launch but queries will return an error.\n")
    else:
        print("✅  Workflow ready.\n")

    demo = build_ui(str(config_path))

    try:
        demo.launch(
            server_name=args.host,
            server_port=args.port,
            share=args.share,
        )
    finally:
        _run_coroutine(_shutdown())


if __name__ == "__main__":
    main()
