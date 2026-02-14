# Learnings

## Environment Setup
- **Issue**: System Python is 3.9.6, but `nanobot` requires `>=3.11`.
- **Solution**: Used `uv` to download and manage Python 3.11.
- **Pattern**: Always check `python --version` against `pyproject.toml` early.
- **Tools**: `uv` is installed and is the preferred tool for environment management here.

## Module 2: Tools & Classes
- **Class Defined**: `ExecTool` (in `nanobot/agent/tools/shell.py`).
- **Key Method**: `execute(self, command, ...)` - This is the function that actually runs the shell command.
- **Concept: Class**: A "Class" is like a blueprint or a template. `ExecTool` is a blueprint for creating a tool that can run commands.
- **Concept: Method**: A "Method" is an action that the blueprint can perform. `execute` is the action of running a command.
- **Inheritance**: `ExecTool(Tool)` means `ExecTool` is a specific *type* of `Tool`. It borrows basic features from the `Tool` blueprint.

## Module 3: The Brain (Loops & Logic)
- **File**: `nanobot/agent/loop.py`.
- **The Heartbeat**: The `while self._running:` loop (Line 94) keeps the agent alive, waiting for messages.
- **Async Magic**: `await asyncio.wait_for(...)` (Line 97) tells Python "Pause here until a message arrives, but feel free to do other work (like responding to other users) in the meantime."
- **Thinking Process**: The `while iteration < self.max_iterations:` loop (Line 163) is where the agent "thinks" and uses tools. It keeps trying tools until it's done or runs out of attempts.

## Final Project
- Created a `hello` command in `nanobot/cli/commands.py`.
- Used `Typer` decorators to expose the function to the CLI.
- Learned that modifications require a restart (or reload) of the CLI to take effect.
