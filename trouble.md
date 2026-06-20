# Known Issues & Troubles

> **Last updated:** 2026-06-20

This file documents known bugs, limitations, and common troubleshooting scenarios for local-cli. Check here before filing a new issue.

---

## Table of Contents

- [Bugs](#bugs)
- [Limitations](#limitations)
- [Thread Safety](#thread-safety)
- [Session Memory](#session-memory)
- [LLM Behavior](#llm-behavior)
- [Integration Gaps](#integration-gaps)
- [Tests & CI](#tests--ci)
- [Cross-Platform](#cross-platform)

---

## Bugs

### B1: Session memory dedup false positive

**Status:** Open
**File:** `local_cli/agent.py` — `_save_session_progress()`
**Impact:** Low — at most one entry is lost per consecutive save

The dedup check compares `merged[-1] == new_entries[-1]` to skip duplicate saves. When the same tool+result combination happens in consecutive saves (e.g., two `bash echo foo` commands in different turns), the result dicts are identical and the save is skipped. This means the **last entry of the current batch is not persisted**, affecting at most one entry per consecutive save.

**Workaround:** None needed — the loss affects at most one entry per save and is rarely noticed.

---

### B2: `pytest` import errors in test suite

**Status:** Open
**File:** `tests/test_skill_proposals.py`
**Impact:** 4 pre-existing test failures (appear every run)

Four tests in `test_skill_proposals.py` fail with `ModuleNotFoundError: No module named 'pytest'` because they use `pytest.raises` and other pytest-specific features, but the project uses `unittest` as its test runner. These tests are never run successfully in CI.

**Workaround:** Install pytest (`pip install pytest`) and run with `pytest`, or skip these 4 tests when using unittest.

---

### B3: Greeting continuation loop (FIXED)

**Status:** Fixed in v0.10.0 (this session)
**Root cause:** Simple greetings like "hai" triggered the Smart continuation logic (Check 4), causing the agent loop to inject "continue working" messages up to 5 times before stopping. The LLM was not instructed to respond with `[TASK COMPLETE]` for casual conversation.
**Fix:** Added `_is_greeting()` function + `_GREETING_WORDS` frozenset in `local_cli/agent.py`. When the user's message is ≤6 words and all words are known greetings (hi, hello, thanks, ok, etc.), the loop breaks naturally before reaching the continuation check.

---

### B4: `_is_greeting("")` vacuous truth (FIXED)

**Status:** Fixed in v0.10.0 (this session)
**Root cause:** Python's `all()` returns `True` for an empty iterable, so `_is_greeting("")` returned `True`.
**Fix:** Added `if not words:` check before the `all()` call.

---

## Limitations

### L1: Limited multilingual greeting detection

**File:** `local_cli/agent.py` — `_GREETING_WORDS`
**Impact:** Non-English greetings still trigger the continuation loop

The `_GREETING_WORDS` frozenset only covers English greetings and acknowledgements (~40 words). Greetings in other languages ("hola", "bonjour", "こんにちは", "你好", etc.) are not recognized and will still cause the agent to loop up to 5 times.

**Workaround:** Extend `_GREETING_WORDS` with additional language-specific greetings.

---

### L2: No linters or formatters configured

**File:** `pyproject.toml`
**Impact:** Code style is enforced only by convention — no automated checks

The project has zero external Python dependencies and does not configure tools like `ruff`, `black`, `pylint`, or `mypy`. Code style consistency relies entirely on manual review.

---

### L3: Tool cache serves stale data for externally modified files

**File:** `local_cli/agent.py` + `local_cli/tool_cache.py`
**Impact:** `read` tool may return outdated content when files are modified by external processes

The tool cache caches `read` results based on file mtime. If a file is modified by an editor, a separate terminal, or a git operation (but not through write/edit tools), the cache may return stale data until the file's mtime changes again.

**Workaround:** Run `/clear` to reset conversation or wait for natural cache invalidation.

---

### L4: No API version pinning for Ollama

**File:** `local_cli/ollama_client.py`
**Impact:** Ollama API changes could break local-cli

The Ollama client makes REST calls to `http://localhost:11434` without pinning an API version. If Ollama introduces breaking changes to its API, local-cli would need updates to match.

---

## Thread Safety

### T1: Non-atomic session memory save

**File:** `local_cli/agent.py` — `_save_session_progress()`
**Impact:** Concurrent sub-agents can overwrite each other's tool history entries

The session memory save operation loads the existing `tool_history` list, extends it with new entries, and saves it back. This `load → extend → save` sequence is not atomic. Two concurrent sub-agents could load the same prior history, extend independently, and the last one to save would overwrite the other's entries.

**Severity:** Low — entries are rarely lost in practice because sub-agents run for different durations and don't typically finish at exactly the same instant.

**Workaround:** Acceptable for current use case. Could be fixed with a file-level lock around the shelve operations.

---

### T2: Sub-agent and main agent share dedup counter

**File:** `local_cli/agent.py` — `_save_session_progress()`
**Impact:** The `_last_tool_count` key in session memory is shared between the main agent loop and all sub-agents. If a sub-agent saves progress between two iterations of the main agent, the main agent's dedup counter can get out of sync, potentially causing duplicate or missed entries.

**Severity:** Low — occurs only during concurrent sub-agent activity.

---

## Session Memory

### S1: Server/web_monitor paths lack session memory

**File:** `local_cli/cli.py` vs `local_cli/server.py` / `local_cli/web_monitor.py`
**Impact:** The JSON-line server and web monitor do not create `SessionMemory` instances. Sub-agents spawned through these paths lose session memory features (cross-turn persistence, SESSION PROGRESS injection).

**Status:** Design gap — not a regression (session memory was never wired for these paths).

---

### S2: No session memory size limit

**File:** `local_cli/session_memory.py`
**Impact:** `tool_history` is capped at 50 entries (`_SESSION_MAX_HISTORY`), but individual entries can grow large through long `result_preview` strings (truncated at 120 chars but still unbounded across many entries). No explicit limit on the number of stored keys or total memory usage.

---

## LLM Behavior

### LLM1: Small models emit inconsistent tool names

**File:** `local_cli/agent.py` — `_TOOL_ALIASES`, `_ARG_ALIASES`
**Impact:** Small models (≤7B parameters) frequently call tools by near-miss names (e.g., `write_file` instead of `write`, `run` instead of `bash`)

Local-cli maintains an extensive alias mapping to resolve these (40+ tool aliases, 30+ argument key aliases). This is a constant maintenance burden as new model families introduce new naming patterns.

**Monitoring:** The alias resolution table at `_TOOL_ALIASES` in `agent.py` grows by ~5-10 entries per model generation.

---

### LLM2: Small models produce code fences instead of tool calls

**File:** `local_cli/agent.py` — `_TOOL_NUDGE_MESSAGES`
**Impact:** Small models often print code in code fences instead of calling write/edit tools

Local-cli has an escalating 3-level nudge system that detects code fences + build keywords and injects progressively firmer reminders to use tools. This is a workaround for model behavior, not a fix.

---

### LLM3: Unclear task completion signals from LLM

**File:** `local_cli/agent.py` — Check 3 (minimum tool calls), Check 4 (smart continuation)
**Impact:** The LLM sometimes says "task done" after zero or one tool call, or hints at more work without calling tools

The agent loop has 5 checks to determine when to stop, plus the `_MIN_TOOL_CALLS_BEFORE_DONE` threshold (3) to challenge premature completion declarations. Despite these safeguards, the LLM still occasionally produces ambiguous signals.

---

## Integration Gaps

### G1: Desktop app Electron build may be out of date

**File:** `desktop/`
**Impact:** The Electron desktop app communicates with the Python backend via the JSON-line server protocol. Changes to the server's message format could break the desktop UI. No automated integration tests exist for the Electron ↔ server protocol.

---

### G2: No end-to-end tests

**Impact:** The `e2e_verify.mjs` script exists but is a manual/visual testing tool (requires Playwright + headed browser). It is not integrated into CI and is not a formal test suite.

---

## Tests & CI

### TC1: 4 pre-existing test failures

**Status:** Open (see B2 above)
**Impact:** `python -m unittest discover -s tests -v` always shows 4 errors

```
ERROR: test_skill_proposals (test_skill_proposals.TestSkillProposals)
ModuleNotFoundError: No module named 'pytest'
```

These tests require pytest fixtures and are incompatible with unittest's test loader.

---

### TC2: Test suite takes ~30-60 seconds

**Impact:** Full test suite has 2,077+ tests. No parallel test execution (unittest does not support it natively).

---

### TC3: No coverage tracking

**Impact:** No code coverage tool is configured. It's unknown what percentage of the codebase is exercised by tests.

---

## Cross-Platform

### X1: Windows path separators

**File:** Multiple — platform-specific code throughout `local_cli/`
**Impact:** The project was primarily developed on Linux/macOS. Some modules use platform-specific tools or assume a Unix environment.

**Known locations:**
- `local_cli/clipboard.py` — uses `pbcopy`/`xclip`/`wl-copy` (macOS/Linux only)
- `local_cli/git_ops.py` — uses `subprocess` with unix-style commands
- `local_cli/tools/bash_tool.py` — shell command execution assumes Unix shell syntax

**Note:** `local_cli/session_memory.py` uses `tempfile.mkdtemp()` which is fully cross-platform — not affected.

---

### X2: Terminal UI color codes on Windows

**File:** `local_cli/stat.py`
**Impact:** ANSI color codes may not render correctly in older Windows terminals (CMD.exe, PowerShell before Windows Terminal). No `colorama` or Windows console API fallback is used.

---

## Contributing

Found a new bug? Please:

1. Check this file first — your issue may already be documented
2. Search existing GitHub Issues
3. File a new issue with:
   - Python version (`python --version`)
   - Ollama version (`ollama --version`)
   - local-cli version (`local-cli --version`)
   - Full error output (use `--debug` flag for extra detail)
   - Steps to reproduce
