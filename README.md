# OpenClaw

An AI agent built on the **NVIDIA AgentIQ / NeMo Agent Toolkit** (`aiqtoolkit`).

OpenClaw is a tool-calling agent wired to a NVIDIA NIM LLM (or any OpenAI-compatible
local model) and equipped with a practical set of built-in tools:

| Tool | Description |
|---|---|
| `web_search` | DuckDuckGo web search (no API key needed) |
| `wiki_search` | Wikipedia article summaries |
| `datetime` | Current UTC date/time |
| `system_info` | Host OS and NVIDIA GPU info |
| `url_fetch` | Retrieve text content from any URL |
| `calculator` | Safe arithmetic (sin, cos, sqrt, log…) |
| `code_runner` | Execute Python snippets *(disabled by default)* |
| `gmail_summary` | Personal-assistant inbox briefing (unread count, senders, follow-ups) |
| `gmail_list` | List recent inbox messages |
| `gmail_read` | Read a full email by ID |
| `gmail_search` | Search Gmail with any search operator |
| `gmail_followup` | Find sent emails with no reply after N days |
| `gmail_mark` | Star an email to flag it for follow-up |

---

## Requirements

- Python 3.11 or newer
- NVIDIA API key ([build.nvidia.com](https://build.nvidia.com)) — *or* a local
  OpenAI-compatible model server (Ollama, vLLM, llama.cpp…)

---

## Web UI

OpenClaw ships a Gradio chat interface that embeds the AgentIQ workflow directly:

```bash
# NVIDIA NIM (cloud) — default
openclaw-ui

# Local model (Ollama / vLLM / llama.cpp)
openclaw-ui --config config_local.yml

# Custom port / public share link
openclaw-ui --port 8080 --share
```

Then open **http://localhost:7860** in your browser.

---

## Quick start

```bash
# 1. Clone and enter the repo
git clone <repo-url>
cd The-Orquestrator-

# 2. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate

# 3. Install OpenClaw (editable) + AgentIQ
pip install -e ".[langchain]"        # pyproject.toml extras
# or explicitly:
pip install aiqtoolkit[langchain] -e .

# 4. Set your NVIDIA API key
cp .env.example .env
# Edit .env and add your NVIDIA_API_KEY

# 5. Run the agent
export $(cat .env | xargs)   # load env vars
aiq run --config_file src/openclaw/configs/config.yml \
        --input "What is the latest news about NVIDIA?"
```

### Using a local model instead

```bash
# Start Ollama (example) with a tool-capable model
ollama pull llama3.3
ollama serve

# Run OpenClaw against it
aiq run --config_file src/openclaw/configs/config_local.yml \
        --input "What is 3.14159 * e^2?"
```

---

## Project layout

```
The-Orquestrator-/
├── pyproject.toml                   # Package definition & entry points
├── .env.example                     # Environment variable template
└── src/
    └── openclaw/
        ├── __init__.py
        ├── register.py              # All tools + agent definitions
        └── configs/
            ├── config.yml           # NVIDIA NIM (cloud) config
            └── config_local.yml     # Local / OpenAI-compatible config
```

---

## Architecture

OpenClaw follows the AgentIQ *everything is a function* model:

```
workflow.yml
    └── workflow: tool_calling_agent
            ├── llm: nim  (meta/llama-3.3-70b-instruct)
            └── tools: [web_search, wiki_search, datetime,
                        system_info, url_fetch, calculator, code_runner]
```

Each tool is a Python `async` generator decorated with `@register_function` and
backed by a Pydantic config class. The AgentIQ CLI discovers them automatically
via the `aiq.components` Python entry point declared in `pyproject.toml`.

---

## Gmail — personal email assistant

OpenClaw can track your Gmail inbox and follow-ups like a personal assistant.

### Setup (one-time)

1. Go to [Google Cloud Console](https://console.cloud.google.com/) and create a project
2. **APIs & Services → Enable APIs** — search and enable **Gmail API**
3. **APIs & Services → Credentials → Create Credentials → OAuth 2.0 Client ID**
   - Application type: **Desktop app** → download the JSON file
4. Save it as `~/.openclaw/gmail_credentials.json`
   *(or set `GMAIL_CREDENTIALS_FILE` env var to a custom path)*
5. Install the Gmail extras and run the auth helper:

```bash
pip install -e ".[gmail]"
python scripts/gmail_setup.py   # opens browser for one-time OAuth consent
```

### Usage

Once authenticated the agent can answer questions like:

- *"Give me my inbox briefing"* → `gmail_summary`
- *"What emails haven't I replied to in 3 days?"* → `gmail_followup`
- *"Search for emails from alice@example.com about the Q1 report"* → `gmail_search`
- *"Read email ID 18e4abc123"* → `gmail_read`
- *"Mark that email for follow-up"* → `gmail_mark`

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `GMAIL_CREDENTIALS_FILE` | `~/.openclaw/gmail_credentials.json` | Path to OAuth2 credentials |
| `GMAIL_TOKEN_FILE` | `~/.openclaw/gmail_token.json` | Where the auth token is cached |
| `GMAIL_USER_ID` | `me` | Gmail address to act as |

---

## Enabling code execution

The `code_runner` tool is disabled by default. To enable it, set `allowed: true`
in the config:

```yaml
functions:
  code_runner:
    _type: openclaw_code_runner
    allowed: true
    timeout_seconds: 10
```

> **Warning:** Only enable code execution in trusted, sandboxed environments.

---

## Extending OpenClaw

Add a new tool in `src/openclaw/register.py`:

```python
class MyToolConfig(FunctionBaseConfig, name="openclaw_my_tool"):
    my_param: str = Field("default", description="My parameter")

@register_function(config_type=MyToolConfig)
async def my_tool(config: MyToolConfig, builder: Builder):
    async def _run(input: str) -> str:
        """Tool docstring shown to the LLM."""
        return f"Result for: {input}"
    yield FunctionInfo.from_fn(_run, description="Short tool description")
```

Then reference it in your `config.yml`:

```yaml
functions:
  my_tool:
    _type: openclaw_my_tool
    my_param: "custom value"

workflow:
  tool_names: [..., my_tool]
```

---

## Tech stack

- [NVIDIA AgentIQ / NeMo Agent Toolkit](https://github.com/NVIDIA/NeMo-Agent-Toolkit) (`aiqtoolkit`)
- [NVIDIA NIM](https://build.nvidia.com) for LLM inference
- [LangChain](https://python.langchain.com) (agent orchestration backend)
- [DuckDuckGo Search](https://pypi.org/project/duckduckgo-search/)
- [Wikipedia API](https://pypi.org/project/wikipedia-api/)
- [httpx](https://www.python-httpx.org/)
