<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://img.shields.io/badge/local--cli-v0.10.0-red?style=for-the-badge&logo=python&logoColor=white&labelColor=333">
    <img alt="local-cli" src="https://img.shields.io/badge/local--cli-v0.10.0-red?style=for-the-badge&logo=python&logoColor=white&labelColor=333">
  </picture>
</p>

<p align="center">
  <strong>Local-first AI coding agent. Zero dependencies. Runs entirely on your machine.</strong>
</p>

<p align="center">
  <a href="#features">Features</a> &nbsp;·&nbsp;
  <a href="#quick-start">Quick Start</a> &nbsp;·&nbsp;
  <a href="#cli-usage">CLI Usage</a> &nbsp;·&nbsp;
  <a href="#slash-commands">Slash Commands</a> &nbsp;·&nbsp;
  <a href="#session-memory">Session Memory</a> &nbsp;·&nbsp;
  <a href="#desktop-app">Desktop App</a> &nbsp;·&nbsp;
  <a href="#architecture">Architecture</a> &nbsp;·&nbsp;
  <a href="#configuration">Configuration</a>
</p>

---

## Table of Contents

- [What is this?](#what-is-this)
- [Features](#features)
- [Quick Start](#quick-start)
- [CLI Usage](#cli-usage)
- [Slash Commands](#slash-commands)
- [Session Memory](#session-memory)
- [Sub-Agent Visual Feedback](#sub-agent-visual-feedback)
- [Tools](#tools)
- [Identity and Memory System](#identity--memory-system)
- [Nudge System](#nudge-system)
- [Skills System](#skills-system)
- [Self-Healing](#self-healing)
- [Desktop App](#desktop-app)
- [Architecture](#architecture)
- [Configuration](#configuration)
- [Development](#development)
- [Tests](#tests)
- [License](#license)

---

## What is this?

**local-cli** is an AI coding agent that runs locally using [Ollama](https://ollama.com). It can read, write, and edit files, run shell commands, search code, execute git operations, create archives, fetch web pages -- all through natural language.

It also supports **Claude API** as an alternative provider, with seamless runtime switching between local and cloud models.

Think of it as a local, offline-capable alternative to cloud-based AI coding assistants -- **with zero external Python dependencies**.

---

## Features

### Autonomous Agent

| Feature | Description |
|---|---|
| **Agent Loop** | Self-directed task execution -- thinks, calls tools, observes results, iterates until completion |
| **Multi-step reasoning** | Breaks complex tasks into steps with structured task tracking |
| **Smart task completion** | 6-level completion check: [TASK COMPLETE] marker, escalating tool-use nudges, minimum tool calls guard, greeting guard, smart continuation hints, max continuation cap |
| **Greeting guard** | Detects simple greetings (hi, thanks, ok) and breaks naturally instead of injecting continuation messages — no more 5-iteration loops on "hai" |
| **Error recovery** | Reads error messages, adapts approach, retries with fallback strategies |
| **Sub-agent orchestration** | Spawns parallel sub-agents with real-time visual feedback (delegation box, progress bar, completion box) |
| **Confirmation flow** | Asks for user approval before destructive operations (force push, hard reset, etc.) |

### Session Memory

| Feature | Description |
|---|---|
| **Cross-turn persistence** | Tool-call progress is automatically saved to a temp file (tempfile + shelve) after every iteration |
| **Session progress injection** | On subsequent turns, the accumulated tool history is injected as a SESSION PROGRESS system message so the LLM remembers what was already done -- even after context compaction |
| **Sub-agent awareness** | Both foreground and background sub-agents contribute to the same shared tool history |
| **Auto-cleanup** | Temp directory is automatically deleted on session exit via atexit -- zero manual cleanup |
| **/session command** | Inspect stored tool history, temp dir path, or clear all session memory |

### File and Code Operations

| Tool | Description |
|---|---|
| read | Read files with line numbers and optional offset/limit |
| write | Create or overwrite files with path validation |
| edit | Precise find-and-replace string substitution with diff output |
| glob | Find files by pattern (*.py, **/*.ts) |
| grep | Search file contents with regex patterns |
| archive | Create and extract zip archives (no external zip/unzip needed) |

### Terminal and Git

| Tool | Description |
|---|---|
| bash | Execute shell commands with dangerous command blocking |
| git | Safe git operations -- clone, add, commit, push, pull, status, log, diff, branch, checkout, stash |
| web_fetch | Fetch and parse web pages |
| todo_write | Track structured task lists |

### Self-Healing and Repair

- **Codebase scanning**: Detects syntax errors, bare exceptions, unused imports
- **Auto-fix engine**: Repairs issues with git checkpoint safety (/heal)
- **Post-fix validation**: Verifies syntax and imports after healing
- **Git rollback**: Undo changes immediately (/undo, /rollback)

### Identity and Memory

- **SOUL.md** -- Define the agent's personality and core values
- **USER.md** -- Set your preferences and communication style
- **GENERAL.md** -- Add project-wide rules and conventions
- **MEMORY.md** -- Persistent memory across sessions

### Project Awareness

- **Directory tree**: Colorized project structure (/structure)
- **Interview mode**: AI asks structured questions about your project (/interview)
- **RAG engine**: Index your codebase for context-aware responses
- **Skills system**: Auto-injects contextual instructions based on trigger keywords
- **Plan management**: Create, track, and review structured plans with /plan big

### Terminal UI

- **Red and golden color theme** with clear visual hierarchy
- **Ollama status indicator** -- green connected / red disconnected at a glance
- **Rich banner** showing model, provider, tools, identity, RAG, and mode
- **Sub-agent visual feedback** -- real-time delegation boxes, pulsing progress bars, completion boxes
- **Color-coded slash commands** -- consistent styling everywhere
- **Session logging** -- every turn auto-saved to .agents/logs/ for debugging

### Provider Support

- **Ollama** (default): Local inference, full privacy, offline-capable
- **Claude API**: Cloud models (Opus, Sonnet, Haiku)
- **LlamaServer**: Third-party server support
- **Runtime switching**: Toggle between providers with /provider
- **40+ curated models** across 6 categories with live search
- **Model presets**: Per-family parameter tuning (temperature, num_ctx, think mode)

### Security

- **Dangerous command blocking**: rm -rf /, fork bombs, dd to devices, curl pipe sh, etc.
- **Risky-command confirmation**: Recursive rm, sudo, force push, kill, shutdown prompt for approval
- **Destructive git guard**: Force push, hard reset, rebase require explicit confirmation
- **Environment sanitization**: Strips API keys and tokens from subprocess environments
- **Path traversal prevention**: Blocks writes outside the project directory
- **Config file limits**: 10KB max, symlink rejection

---

## Quick Start

### Prerequisites

- **Python 3.10+**
- **Ollama** (install from ollama.com)
- **Git** (for checkpoint/rollback features)

### Install and Run

```bash
# Clone the repository
git clone https://github.com/lutelute/local-cli.git
cd local-cli

# Run directly (no pip install needed)
python -m local_cli

# Or install as a command
pip install -e .
local-cli
```

### First Launch

On first launch, local-cli will:

1. Check that Ollama is running (shows green/red status)
2. Display a welcome banner with model, tools, and provider info
3. Create a temporary session memory store (auto-deleted on exit)
4. Drop you into the interactive REPL
5. Show nudges for pending proposals and missing identity files

```
+------------------------------------------+
|        local-cli v0.10.0                  |
+------------------------------------------+
Model:   qwen3.5:9b
Ollama:  connected
Provider: ollama
Tools:   bash, read, write, edit, glob, grep, web_fetch, todo_write, ask_user, git, archive
Mode:    agent
```

Type /help to see all commands.

---

## Session Memory

local-cli includes a **session-scoped temporary memory** system that persists tool-call progress across REPL turns within a single session.

### How It Works

```
Session start -> SessionMemory() creates /tmp/local-cli-session-XXXXX/
                                                        |
agent_loop() -> saves tool summaries to shelve DB after every iteration
                                                        |
Next turn -> agent_loop() loads prior tool_history from shelve
              |
         Injects as system message:
         --- SESSION PROGRESS ---
           [read] Successfully read calculator.py
           [write] Wrote 10 bytes to calculator.py
           [bash] Tests passed!
         Continue working. Do NOT redo completed steps.
         --- END SESSION PROGRESS ---
              |
         LLM sees context even after compaction
                                                        |
Session exit -> atexit -> shutil.rmtree() deletes temp dir
```

### Data stored on disk

```
/tmp/
  local-cli-session-abc123/
    session_memory.dat     <- shelve database
    session_memory.dir
    session_memory.bak
```

### Keys stored

| Key | Type | Purpose |
|---|---|---|
| tool_history | list[dict] | Chronological log of every tool call this session (tool name + truncated result preview), capped at 50 |
| _last_tool_count | int | Internal dedup counter |

### Sub-agent integration

Both **foreground** and **background** sub-agents contribute to the same shared tool_history. When a sub-agent spawns (agent tool), it receives the same SessionMemory instance. Its tool calls are saved, so the main agent loop sees what sub-agents have done -- even after context compaction.

### Inspecting session memory

Use /session to:
- View the temp directory path
- See all stored keys
- Browse tool history entries with per-entry previews (first 8 + last 4 with N more separator for large histories)
- Clear all stored data with /session clear

### Auto-cleanup

The temp directory is registered with atexit and automatically deleted when the process exits -- even on crash. No manual cleanup needed.

---

## Sub-Agent Visual Feedback

When the LLM spawns a sub-agent via the agent tool, real-time visual feedback is printed to stderr:

```
  --- Spawning sub-agent ---
  ---------------------------
  Why:      Fix calculator bug
  Model:    qwen3.5:9b
  Prompt:   Read the calculator.py file, identify the bug...
  ---------------------------
  >> Sub-agent: Fix calculator bug [progress bar pulsing]
  --- Sub-agent complete ---
  ---------------------------
  Status:   success
  Duration: 12.3s
  Tools:    4 calls
  Result:   Fixed the NameError. Tests pass.
  ---------------------------
```

Three stages:
1. **Delegation box** (green border) -- explains why the sub-agent was spawned, which model it uses, and a prompt preview
2. **Pulsing progress bar** (amber/green) -- shows elapsed time while the sub-agent works
3. **Completion box** (green for success, red for error) -- shows status, duration, tool call count, and result preview

---

## CLI Usage

### Basic Usage

```bash
# Default model
local-cli

# Choose a model at startup
local-cli --select-model

# Use a specific model
local-cli --model qwen3:8b

# Enable RAG for codebase-aware responses
local-cli --rag --rag-path ./src

# Use Claude API
export ANTHROPIC_API_KEY=sk-ant-...
local-cli --provider claude
```

### CLI Flags

| Flag | Env Var | Default | Description |
|------|---------|---------|-------------|
| --model | LOCAL_CLI_MODEL | qwen3.5:9b | Model to use |
| --provider | LOCAL_CLI_PROVIDER | ollama | LLM provider |
| --debug | LOCAL_CLI_DEBUG | false | Debug output |
| --rag | -- | false | Enable RAG |
| --rag-path | -- | . | Directory to index |
| --rag-topk | -- | 5 | RAG results per query |
| --select-model | -- | false | Interactive model picker |
| --server | -- | false | JSON-line server mode (for desktop GUI) |
| --web-monitor | -- | false | Web dashboard with SSE streaming |
| --web-port | -- | 7070 | Port for web monitor |
| --bench | -- | false | Run quick benchmark |
| --think-mode | LOCAL_CLI_THINK_MODE | false | Enable thinking mode for supported models |
| --init-agents | -- | false | Create .agents/ directory with templates |
| --yes / -y | -- | false | Auto-approve risky commands |
| --num-ctx | LOCAL_CLI_NUM_CTX | 8192 | Context window size |
| --temperature | LOCAL_CLI_TEMPERATURE | model-specific | Sampling temperature |

---

## Slash Commands

All commands are available from the interactive REPL.

### Core Commands

| Command | Description |
|---|---|
| /help | Show all available commands |
| /exit / /quit | Exit the REPL |
| /clear | Clear conversation history |
| /model <name> | Switch to a different model |
| /status | Show model, messages, Ollama connection, mode |
| /provider [name] | Switch or show the active LLM provider |

### File and Code

| Command | Description |
|---|---|
| /heal | Scan codebase for bugs and auto-fix |
| /structure [depth] | Show project directory tree |
| /context | Show context window usage (messages, tokens, compaction) |
| /diff | Show uncommitted changes in working tree |

### Git and Checkpoints

| Command | Description |
|---|---|
| /checkpoint [msg] | Create a git checkpoint (tagged commit) |
| /rollback [tag] | Roll back to a checkpoint |
| /undo | Undo the most recent file modifications |

### Planning and Ideation

| Command | Description |
|---|---|
| /plan | Show, create, or update plans |
| /plan big | Big-picture overview of all plans with progress bars |
| /ideate | Enter brainstorming (tool-free) mode |
| /interview | Start interview mode -- AI asks about your project |

### Identity and Memory

| Command | Description |
|---|---|
| /identity | Show loaded identity files (SOUL.md, USER.md, etc.) |
| /memory | Manage memory proposals -- propose, approve, reject |
| /improve | Manage improvement proposals for identity files |
| /knowledge | Save, load, or list knowledge items |
| /nudge | Show startup-style nudges (pending proposals, missing files) |

### Session Memory

| Command | Description |
|---|---|
| /session | Show session memory contents: temp directory path, stored keys, and tool history with per-entry previews |
| /session clear | Clear all stored session memory data |

### Models

| Command | Description |
|---|---|
| /models | Open interactive model selector (TUI) |
| /install <model> | Pull/install a model from Ollama registry |
| /uninstall <model> | Delete a model from Ollama |
| /info <model> | Show model details and capabilities |
| /running | List models currently loaded in VRAM |
| /brain [model] | Set or show the orchestrator brain model |
| /registry | Show model-to-task routing registry |

### Session and Debugging

| Command | Description |
|---|---|
| /save | Save the current session |
| /log | Show recent session logs for debugging |
| /copy | Copy last assistant response to clipboard |
| /usage | Show per-message token usage and session totals |
| /agents | List background sub-agent status |

### Management

| Command | Description |
|---|---|
| /skills | Manage skills -- list, show, propose, approve, reject |
| /queue <cmd> | Queue command to run after current agent finishes |
| /bg <cmd> | Run command in background mode |
| /stop | Stop the running agent |
| /update | Check for updates and pull the latest version |

---

## Tools

local-cli comes with **11 built-in tools** that the LLM can call autonomously:

| Tool | Description | Cacheable |
|---|---|---|
| bash | Execute shell commands (with security guards) | No |
| read | Read file contents with line numbers | Yes |
| write | Create or overwrite files | No |
| edit | Find-and-replace string editing | No |
| glob | Find files by pattern | Yes |
| grep | Search file contents with regex | Yes |
| web_fetch | Fetch and parse web pages | Yes |
| todo_write | Track structured task lists | No |
| ask_user | Ask the user a question | No |
| git | Safe git operations (clone, add, commit, push, pull, etc.) | No |
| archive | Create and extract zip archives | No |
| agent | Spawn sub-agents for parallel task execution | No |

### Tool Aliases

The agent loop automatically resolves common near-miss tool names from small models:

- write_file, create_file and modify_file → write
- run, shell, exec and command → bash
- find, searchfiles and list → glob
- search, findinfiles and find_in_files → grep
- curl, fetch, wget and download → web_fetch

---

## Identity and Memory System

local-cli supports a rich identity system through files in the .agents/ directory:

```
.agents/
  SOUL.md          # Agent's personality, values, and core identity
  USER.md          # Your preferences, communication style, and goals
  GENERAL.md       # Project-wide rules and conventions
  MEMORY.md        # Persistent memory appended over time
  proposals/       # Pending memory/skill/improvement proposals
```

Use /identity to see which files are loaded, and /improve to propose changes.

Run local-cli --init-agents to generate default templates.

---

## Nudge System

On startup (and via /nudge command), local-cli checks for:

1. **Missing MEMORY.md** -- Suggests creating one for persistent memory
2. **Default USER.md** -- Alerts when the template still has placeholder content
3. **Pending memory proposals** -- Reminds to review and approve
4. **Pending skill proposals** -- Reminds to review and approve
5. **Pending improvement proposals** -- Reminds to review and approve

---

## Skills System

Skills are reusable instruction sets auto-injected based on trigger keywords in your input:

```
.agents/skills/
  django-api/
    SKILL.md         # triggers: [django, REST API, DRF]
  react-patterns/
    SKILL.md         # triggers: [react, component, hook]
  code-review/
    SKILL.md         # triggers: [review, PR, code quality]
```

### SKILL.md Format

```markdown
---
name: django-api
triggers: [django, REST API, DRF, serializer]
description: Django REST Framework conventions and patterns
---

## Guidelines

- Use ModelSerializer for standard CRUD
- Use ViewSets with routers for URL configuration
- Apply permission classes at the view level
```

When you mention a trigger keyword, the matching skill's content is injected into the conversation context automatically. Matching is case-insensitive substring matching, and multiple skills can match a single input.

See [docs/skills.md](docs/skills.md) for the full guide.

---

## Self-Healing

The /heal command runs a multi-phase self-diagnosis:

1. **Scan**: Checks all Python files for syntax errors, bare except: clauses, and unused imports
2. **Auto-fix**: Creates a git checkpoint, then attempts to repair issues (e.g., except: → except Exception:)
3. **Validate**: Runs syntax checks and module import tests post-fix

---

## Desktop App

local-cli includes an **Electron desktop app** with a terminal-style GUI.

### Features

- **Streaming chat** with real-time tool call display
- **Model picker** -- Catalog (curated) + Discover (live search)
- **Provider switching** -- Toggle between Ollama and Claude
- **File explorer** -- Browse project files in the sidebar
- **File viewer** -- Preview files without leaving the app
- **Settings panel** -- App and backend updates, keyboard shortcuts
- **Auto-update** -- Checks GitHub Releases on startup

### Run from Source

```bash
cd desktop
npm install
npm run dev       # Development (Vite HMR)
npm run build    # Production build
```

### Build Installers

```bash
npm run build:mac    # macOS (DMG)
npm run build:win    # Windows (NSIS installer)
npm run build:linux  # Linux (AppImage + .deb)
```

### Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| Cmd/Ctrl + , | Settings |
| Cmd/Ctrl + B | Toggle file explorer |
| Escape | Stop generation / Close dialog |
| Shift + Enter | New line in input |
| Enter | Send message |

---

## Architecture

```
local-cli/
  local_cli/                        # Core Python package (zero dependencies)
    __init__.py                   # Package metadata, __version__
    __main__.py                   # Entry point: orchestrates startup
    agent.py                      # Agent loop (LLM ↔ tools, streaming, compaction, session progress)
    cli.py                        # REPL, slash commands, arg parsing, welcome banner
    config.py                     # Configuration (CLI > env > file > defaults)
    session_memory.py             # Session-scoped temporary memory (tempfile + shelve)
    orchestrator.py               # Multi-provider orchestration
    ollama_client.py              # Ollama REST API client
    session.py                    # Session persistence (JSONL)
    plan_manager.py               # Structured plan management (markdown)
    security.py                   # Dangerous/risky command detection, env sanitization
    stat.py                       # Status display, ANSI colors, agent controller
    prompts.py                    # System prompt builder (includes Rule 12 for session progress)
    identity.py                   # SOUL.md / USER.md / GENERAL.md loader
    memory_proposals.py           # Memory proposal management
    skill_proposals.py            # Skill proposal management
    self_improvement.py           # Improvement proposals and nudge engine
    self_heal.py                  # Self-healing engine (scan, fix, validate)
    skills.py                     # Skill discovery and matching
    knowledge.py                  # Persistent knowledge store
    rag.py                        # RAG engine (SQLite + embeddings)
    git_ops.py                    # Git checkpoint/rollback operations
    model_catalog.py              # 40+ curated models
    model_search.py               # Live search from ollama.com
    model_manager.py              # Install / delete / info
    model_registry.py             # Task-to-model routing
    model_selector.py             # Interactive TUI picker
    model_presets.py              # Per-family parameter tuning
    token_tracker.py              # Per-message token usage tracking
    tool_cache.py                 # Tool result caching (read/glob/grep)
    sub_agent.py                  # Sub-agent runner with session memory integration
    spinner.py                    # Terminal spinner animation
    ideation.py                   # Brainstorming / ideation engine
    clipboard.py                  # System clipboard integration
    health_check.py               # Startup health checks
    diff_preview.py               # Unified diff formatter
    updater.py                    # Self-update (git pull)
    web_monitor.py                # Web-based agent monitor (SSE)
    system_info.py                # Hardware detection
    server.py                     # JSON-line server for desktop GUI
    bench.py                      # Quick benchmark runner
    tools/                        # 11 built-in agent tools
      __init__.py                 # Tool registry (get_default_tools)
      base.py                    # Abstract Tool base class
      bash_tool.py               # Shell command execution
      read_tool.py               # File reading
      write_tool.py              # File creation/overwrite
      edit_tool.py               # Find-and-replace editing
      glob_tool.py               # File pattern search
      grep_tool.py               # Content search (regex)
      web_fetch_tool.py          # URL fetching
      todo_tool.py               # Task list tracking
      ask_user_tool.py           # User prompts
      agent_tool.py              # Sub-agent spawning with visual feedback and session memory
      git_tool.py                # Safe git operations
      archive_tool.py            # Zip/unzip (pure Python)
    providers/                   # LLM provider adapters
      base.py                    # Abstract LLMProvider
      ollama_provider.py         # Ollama adapter
      claude_provider.py         # Claude API adapter
      llama_server_provider.py   # LlamaServer adapter
      message_converter.py       # Format normalization
      sse_parser.py              # SSE streaming parser
  desktop/                          # Electron + React + Vite desktop app
  tests/                            # 2050+ tests (unittest)
  docs/                             # Documentation (prompts.md, skills.md)
  scripts/                          # Utility scripts
 .agents/                          # Agent metadata (auto-created)
```

---

## Configuration

Configuration is resolved in order: *CLI flags > environment variables > config file > defaults*.

### Config file: .local-cli.json or ~/.config/local-cli/config.json

```json
{
  "model": "qwen3.5:9b",
  "provider": "ollama",
  "num_ctx": 8192,
  "temperature": 0.3,
  "debug": false
}
```

### Environment variables

- LOCAL_CLI_MODEL -- Model name
- LOCAL_CLI_PROVIDER -- Provider (ollama | claude | llamaserver)
- LOCAL_CLI_DEBUG -- Enable debug output
- LOCAL_CLI_NUM_CTX -- Context window size
- LOCAL_CLI_TEMPERATURE -- Sampling temperature
- LOCAL_CLI_THINK_MODE -- Enable think mode
- ANTHROPIC_API_KEY -- Claude API key

---

## Development

```bash
# Run from source
python -m local_cli

# Install in editable mode
pip install -e .

# Run the desktop app
cd desktop && npm install && npm run dev
```

### Code style

The project follows standard Python conventions and has zero external dependencies. No linters or formatters are required.

---

## Tests

```bash
# Run all tests
python -m unittest discover -s tests -v

# Run specific test files
python -m unittest tests.test_agent tests.test_session_memory -v
```

The test suite includes **2077+ tests** covering:
- Agent loop (completion detection, nudges, tool aliases, session progress)
- All 11 tools (bash, read, write, edit, glob, grep, web_fetch, git, archive, agent, todo)
- Session memory (creation, save, load, clear, auto-cleanup)
- Sub-agent runner (foreground and background execution, session memory propagation)
- Exit conditions -- max iterations, task complete marker, no-tool fallback
- Provider adapters (Ollama, Claude, LlamaServer)
- Security (dangerous command blocking, path traversal prevention)
- Model management (install, delete, search, registry)
- RAG engine, identity system, skills, knowledge, plans, nudges, self-healing
- Utilities (config, spinner, token tracker, tool cache, diff preview, clipboard)

---

## License

MIT
