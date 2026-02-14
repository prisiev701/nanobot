# Draft: Nanobot Code Analysis

## Initial Request
- User wants to analyze the 'nanobot' code.

## Findings
- **Architecture**: Hybrid Python (Core) + TypeScript (WhatsApp Bridge).
- **Core Framework**: Python 3.11+, using `typer` for CLI, `litellm` for AI, `pydantic` for config.
- **Agent System**: 
  - `AgentLoop` (`nanobot/agent/loop.py`) handles the OODA loop (Observe-Orient-Decide-Act).
  - Uses `MessageBus` for async communication.
  - Supports `subagents` via `SpawnTool`.
- **Skills System**:
  - Located in `nanobot/skills/`.
  - Format: `SKILL.md` with YAML frontmatter + Markdown instructions.
  - OpenClaw-compatible.
- **Integrations**:
  - Telegram: Built-in Python via `python-telegram-bot`.
  - WhatsApp: External Node.js bridge (`nanobot/bridge`) using `@whiskeysockets/baileys`.

## Tech Stack
- **Python**: Typer, LiteLLM, Pydantic, Loguru.
- **Node.js**: Baileys (WhatsApp), Express/WS (Bridge server).
- **Deployment**: Docker support included.

## Open Questions
- Analysis complete. Waiting for user's next move (implementation or exit).


