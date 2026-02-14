# Learning Plan: Mastering Nanobot for Beginners

## TL;DR

> **Quick Summary**: A step-by-step interactive journey to understand the `nanobot` codebase, designed for a total beginner. We will learn Python concepts *by reading and modifying* the actual project code.
> 
> **Deliverables**:
> - A working local environment.
> - A modified `nanobot` CLI with your custom command.
> - Understanding of key Python concepts (Functions, Imports, Async).
> 
> **Estimated Effort**: Medium (Multiple sessions).
> **Parallel Execution**: NO - Sequential learning path.

---

## Context

### User Goal
- **Primary**: Understand how `nanobot` works internally.
- **Secondary**: Contribute to the codebase.
- **Level**: Total Beginner (New to programming).

### Teaching Strategy
We will use the **"Code-First"** approach:
1.  **Observe**: Look at a specific file.
2.  **Explain**: Understand the Python concept behind it.
3.  **Tinker**: Make a small, safe change to see what happens.
4.  **Verify**: Run the code to confirm understanding.

---

## Work Objectives

### Core Objective
Demystify the `nanobot` architecture by dissecting it layer by layer, starting from the CLI (Entry Point) down to the Agent Loop (Brain).

### Definition of Done
- [ ] User can run `nanobot --version` and see their custom message.
- [ ] User can explain what `commands.py` does.
- [ ] User can explain what a "Tool" is in the code.
- [ ] User has added a new simple command to the project.

---

## Verification Strategy (Agent-Executed)

> **Role of the Agent**: Since this is a learning plan, the Agent (Sisyphus) will act as your **Tutor**.
> It will not "do the work" for you, but it will *set up* the exercises and *verify* your solution.

### Verification Scenarios

**Scenario 1: Verify Environment**
- **Tool**: Bash
- **Check**: `python --version`, `pip list`, `nanobot --help`.

**Scenario 2: Verify CLI Modification**
- **Tool**: Interactive Bash
- **Action**: Run the modified `nanobot` command.
- **Assert**: Output contains the user's custom string.

---

## TODOs (Learning Modules)

- [x] 1. **Setup & Verification**
    **Goal**: Ensure the playground is ready.
    **Concepts**: Terminal, Virtual Environments, Commands.
    **Recommended Agent**: `quick` (Skills: `bash`)
    **Steps**:
    - Check Python version (`python3 --version`).
    - Install `nanobot` in editable mode (`pip install -e .`).
    - Run `nanobot --help` to confirm it works.
    **Acceptance Criteria**:
    - `nanobot --help` returns exit code 0.

- [x] 2. **Module 1: The Entry Point (Functions & Decorators)**
    **Goal**: Understand how the terminal command `nanobot` talks to the Python code.
    **File**: `nanobot/cli/commands.py`
    **Concepts**:
    - **Imports**: `import asyncio` (Getting tools from the shelf).
    - **Functions**: `def main(...)` (Reusable blocks of code).
    - **Decorators**: `@app.command()` (Tagging a function as a command).
    **Exercise**:
    - Locate the `version_callback` function.
    - Change the print message from `nanobot v{version}` to `nanobot v{version} - Hacked by [YourName]`.
    - Run `nanobot --version`.
    **Reference**:
    - `nanobot/cli/commands.py:21` - The version callback function.

- [x] 3. **Module 2: The Tools (Classes & Methods)**
    **Goal**: Understand how Nanobot interacts with the world.
    **File**: `nanobot/agent/tools/spawn.py` (or similar simple tool).
    **Concepts**:
    - **Classes**: `class SpawnTool` (A blueprint for an object).
    - **Methods**: `def run(...)` (Actions the object can take).
    **Exercise**:
    - Read `spawn.py` to see how it defines a tool.
    - We will ask the agent to explain what "Class" means in this context.

- [x] 4. **Module 3: The Brain (Loops & Logic)**
    **Goal**: Peak into the core logic.
    **File**: `nanobot/agent/loop.py`
    **Concepts**:
    - **While Loop**: `while True:` (Doing things forever until stopped).
    - **Async/Await**: `await` (Waiting for a slow task without freezing).
    **Exercise**:
    - Identify the main `while` loop that keeps the agent running.
    - Identify where it "waits" for the user to type something.

- [x] 5. **Final Project: "Hello World" Command**
    **Goal**: Your first contribution.
    **Task**:
    - Create a new command `nanobot hello`.
    - It should accept a name argument (e.g., `nanobot hello --name Prometheus`).
    - It should print `Hello, Prometheus! Welcome to the code.`
    **Reference**:
    - `nanobot/cli/commands.py` (Use existing commands as a template).

---

## Success Criteria

### Final Checklist
- [ ] User has modified `nanobot` locally.
- [ ] `nanobot hello` command works.
- [ ] User understands basic project structure.
