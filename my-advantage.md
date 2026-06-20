# 🧠 local-cli Agent — Capabilities & Advantages

> *A local-first, offline-capable AI coding agent powered by Ollama.*

---

## 🎯 Core Capabilities

### 🤖 Autonomous Code Agent
- **Agent Loop**: Self-directed task execution — thinks, uses tools, observes results, iterates until completion
- **Multi-step reasoning**: Breaks complex tasks into steps with task tracking (`todo_write`)
- **Error recovery**: Reads error messages, adapts approach, retries with fallback strategies
- **Sub-agent orchestration**: Spawns parallel sub-agents for file search, code search, web research, and more

### 📂 File & Code Operations
| Capability | Description |
|---|---|
| **Read files** | Read any file with line numbers, optional offset/limit |
| **Write files** | Create or overwrite files with path validation |
| **Edit files** | Precise find-and-replace string substitution |
| **Glob search** | Find files by pattern (`*.py`, `**/*.ts`) |
| **Grep search** | Search file contents with regex patterns |
| **Multi-file awareness** | Understands and modifies across file boundaries |

### 🖥️ Terminal Integration
- **Shell execution**: Run any command via `bash` tool (with dangerous command blocking)
- **Background tasks**: Start long-running commands in background (`/bg`)
- **Command queue**: Queue commands to run after current task finishes (`/queue`)
- **Stop execution**: Interrupt running agent instantly (`/stop`)
- **Dedicated tools for common ops**: `git`, `archive` (zip/unzip), `curl` (via bash/web_fetch), `wget` (via bash)

### 🔧 Self-Healing & Repair
- **Codebase scanning**: Detects syntax errors, bare exceptions, unused imports
- **Auto-fix engine**: Attempts to repair issues with git checkpoint safety
- **Rollback safety**: Creates git checkpoints before any fix attempt (`/heal`)
- **Post-fix validation**: Verifies syntax and imports after healing

### 🏗️ Project Awareness
- **Directory tree**: Visualises project structure with color (`/structure`)
- **Interview mode**: AI asks structured questions to learn about your project (`/interview`)
- **Identity system**: Understands project context via SOUL.md, USER.md, GENERAL.md files
- **Skills system**: Auto-injects contextual instructions based on trigger keywords
- **RAG engine**: Indexes your codebase for context-aware responses
- **Plan big picture**: Overview of all plans with progress bars (`/plan big`)

### 🎨 Terminal UI
- **Color-coded REPL**: Red & golden theme with clear visual hierarchy
- **Ollama status**: Instant visual feedback on connection state (green/red indicator)
- **Rich status bar**: Shows model, message count, running tasks with elapsed time
- **Tidy output**: Consistent styling across all slash commands

### 🔌 Provider Support
- **Ollama** (default): Local inference, full privacy, offline-capable
- **Claude API**: Cloud models (Opus, Sonnet, Haiku)
- **Runtime switching**: Toggle between providers with `/provider`
- **40+ curated models** across 6 categories with live search

### 📋 Session & Memory
- **Session persistence**: Save/load conversations as JSONL files (`/save`)
- **Knowledge store**: Persistent key-value memory (`/knowledge`)
- **Memory proposals**: User-approved persistent notes (`/memory`)
- **Git checkpoints**: Tagged snapshots before risky edits (`/checkpoint`)

### 📊 Monitoring & Debugging
- **Health checks**: Startup validation of Ollama, model, disk space
- **System info**: Hardware detection and model recommendations
- **Token tracking**: Per-message usage and session totals (`/usage`)
- **Context window**: Message/token count with compaction status (`/context`)
- **Diff preview**: See uncommitted changes (`/diff`)
- **Session logging**: Every turn auto-saved to `.agents/logs/` for debugging (`/log`)
- **Plan big picture**: Visual overview of all plans with progress bars (`/plan big`)

### 🔐 Security
- Dangerous command blocking (`rm -rf /`, fork bombs, etc.)
- Risky-command confirmation prompts
- Environment sanitization (strips API keys from subprocesses)
- Path traversal prevention
- Config file size limits

---

## 🎯 Key Advantages Over Cloud-Based Agents

### ✅ **Truly Local & Offline**
- Zero dependencies on cloud APIs (when using Ollama)
- Works without internet — ideal for sensitive/air-gapped environments
- No data leaves your machine

### ✅ **Zero Dependencies**
- Python stdlib only — no `pip install` for core CLI
- Single-file tools, no heavy framework required

### ✅ **Full Control**
- Every tool call is transparent
- Sub-agent spawning for parallelism
- Git-backed rollback at every step
- Open-source, forkable, auditable

### ✅ **Customizable Identity**
- Define the agent's personality with `SOUL.md`
- Set your preferences with `USER.md`
- Add project rules with `GENERAL.md`
- Agent remembers across sessions with `MEMORY.md`

### ✅ **Cost-Effective**
- No per-token API costs with local models
- Run 24/7 without budget concerns
- Choose your model based on task complexity

---

## ⚙️ Quick Reference

| Command | What it does |
|---|---|
| `/help` | Show all commands |
| `/status` | Show model, messages, Ollama connection |
| `/model <name>` | Switch model |
| `/heal` | Scan & repair codebase issues |
| `/structure [depth]` | Show project file tree |
| `/plan create <title>` | Create a structured plan |
| `/checkpoint` | Save a git checkpoint |
| `/rollback [tag]` | Roll back to checkpoint |
| `/diff` | Show uncommitted changes |
| `/plan big` | Show big-picture plan overview with progress |
| `/log` | Show recent session logs for debugging |
| `/context` | Show context usage |
| `/usage` | Show token usage |
| `/save` | Save session |
| `/knowledge` | Manage persistent knowledge |
| `/skills` | Manage auto-discovered skills |

---

*Built with ❤️ for developers who want AI assistance without compromise.*
