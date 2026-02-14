"""CLI commands for nanobot."""

import asyncio
import os
import signal
from pathlib import Path
import select
import sys

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table
from rich.text import Text

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from prompt_toolkit.patch_stdout import patch_stdout

from nanobot import __version__, __logo__

app = typer.Typer(
    name="nanobot",
    help=f"{__logo__} nanobot - Personal AI Assistant",
    no_args_is_help=True,
)

console = Console()
EXIT_COMMANDS = {"exit", "quit", "/exit", "/quit", ":q"}

# ---------------------------------------------------------------------------
# CLI input: prompt_toolkit for editing, paste, history, and display
# ---------------------------------------------------------------------------

_PROMPT_SESSION: PromptSession | None = None
_SAVED_TERM_ATTRS = None  # original termios settings, restored on exit


def _flush_pending_tty_input() -> None:
    """Drop unread keypresses typed while the model was generating output."""
    try:
        fd = sys.stdin.fileno()
        if not os.isatty(fd):
            return
    except Exception:
        return

    try:
        import termios

        termios.tcflush(fd, termios.TCIFLUSH)
        return
    except Exception:
        pass

    try:
        while True:
            ready, _, _ = select.select([fd], [], [], 0)
            if not ready:
                break
            if not os.read(fd, 4096):
                break
    except Exception:
        return


def _restore_terminal() -> None:
    """Restore terminal to its original state (echo, line buffering, etc.)."""
    if _SAVED_TERM_ATTRS is None:
        return
    try:
        import termios

        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, _SAVED_TERM_ATTRS)
    except Exception:
        pass


def _init_prompt_session() -> None:
    """Create the prompt_toolkit session with persistent file history."""
    global _PROMPT_SESSION, _SAVED_TERM_ATTRS

    # Save terminal state so we can restore it on exit
    try:
        import termios

        _SAVED_TERM_ATTRS = termios.tcgetattr(sys.stdin.fileno())
    except Exception:
        pass

    history_file = Path.home() / ".nanobot" / "history" / "cli_history"
    history_file.parent.mkdir(parents=True, exist_ok=True)

    _PROMPT_SESSION = PromptSession(
        history=FileHistory(str(history_file)),
        enable_open_in_editor=False,
        multiline=False,  # Enter submits (single line mode)
    )


def _print_agent_response(response: str, render_markdown: bool) -> None:
    """Render assistant response with consistent terminal styling."""
    content = response or ""
    body = Markdown(content) if render_markdown else Text(content)
    console.print()
    console.print(f"[cyan]{__logo__} nanobot[/cyan]")
    console.print(body)
    console.print()


def _is_exit_command(command: str) -> bool:
    """Return True when input should end interactive chat."""
    return command.lower() in EXIT_COMMANDS


async def _read_interactive_input_async() -> str:
    """Read user input using prompt_toolkit (handles paste, history, display).

    prompt_toolkit natively handles:
    - Multiline paste (bracketed paste mode)
    - History navigation (up/down arrows)
    - Clean display (no ghost characters or artifacts)
    """
    if _PROMPT_SESSION is None:
        raise RuntimeError("Call _init_prompt_session() first")
    try:
        with patch_stdout():
            return await _PROMPT_SESSION.prompt_async(
                HTML("<b fg='ansiblue'>You:</b> "),
            )
    except EOFError as exc:
        raise KeyboardInterrupt from exc


def version_callback(value: bool):
    if value:
        console.print(f"{__logo__} nanobot v{__version__} - Hacked by Atlas")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(None, "--version", "-v", callback=version_callback, is_eager=True),
):
    """nanobot - Personal AI Assistant."""
    pass


# ============================================================================
# Onboard / Setup
# ============================================================================


@app.command()
def onboard():
    """Initialize nanobot configuration and workspace."""
    from nanobot.config.loader import get_config_path, save_config
    from nanobot.config.schema import Config
    from nanobot.utils.helpers import get_workspace_path

    config_path = get_config_path()

    if config_path.exists():
        console.print(f"[yellow]Config already exists at {config_path}[/yellow]")
        if not typer.confirm("Overwrite?"):
            raise typer.Exit()

    # Create default config
    config = Config()
    save_config(config)
    console.print(f"[green]✓[/green] Created config at {config_path}")

    # Create workspace
    workspace = get_workspace_path()
    console.print(f"[green]✓[/green] Created workspace at {workspace}")

    # Create default bootstrap files
    _create_workspace_templates(workspace)

    console.print(f"\n{__logo__} nanobot is ready!")
    console.print("\nNext steps:")
    console.print("  1. Add your API key to [cyan]~/.nanobot/config.json[/cyan]")
    console.print("     Get one at: https://openrouter.ai/keys")
    console.print('  2. Chat: [cyan]nanobot agent -m "Hello!"[/cyan]')
    console.print(
        "\n[dim]Want Telegram/WhatsApp? See: https://github.com/HKUDS/nanobot#-chat-apps[/dim]"
    )


def _create_workspace_templates(workspace: Path):
    """Create default workspace template files."""
    templates = {
        "AGENTS.md": """# Agent Instructions

You are a helpful AI assistant. Be concise, accurate, and friendly.

## Guidelines

- Always explain what you're doing before taking actions
- Ask for clarification when the request is ambiguous
- Use tools to help accomplish tasks
- Remember important information in memory/MEMORY.md; past events are logged in memory/HISTORY.md
""",
        "SOUL.md": """# Soul

I am nanobot, a lightweight AI assistant.

## Personality

- Helpful and friendly
- Concise and to the point
- Curious and eager to learn

## Values

- Accuracy over speed
- User privacy and safety
- Transparency in actions
""",
        "USER.md": """# User

Information about the user goes here.

## Preferences

- Communication style: (casual/formal)
- Timezone: (your timezone)
- Language: (your preferred language)
""",
    }

    for filename, content in templates.items():
        file_path = workspace / filename
        if not file_path.exists():
            file_path.write_text(content)
            console.print(f"  [dim]Created {filename}[/dim]")

    # Create memory directory and MEMORY.md
    memory_dir = workspace / "memory"
    memory_dir.mkdir(exist_ok=True)
    memory_file = memory_dir / "MEMORY.md"
    if not memory_file.exists():
        memory_file.write_text("""# Long-term Memory

This file stores important information that should persist across sessions.

## User Information

(Important facts about the user)

## Preferences

(User preferences learned over time)

## Important Notes

(Things to remember)
""")
        console.print("  [dim]Created memory/MEMORY.md[/dim]")

    history_file = memory_dir / "HISTORY.md"
    if not history_file.exists():
        history_file.write_text("")
        console.print("  [dim]Created memory/HISTORY.md[/dim]")

    # Create skills directory for custom user skills
    skills_dir = workspace / "skills"
    skills_dir.mkdir(exist_ok=True)


def _make_provider(config):
    """Create LLM provider from config. Prefers Antigravity if enabled + authenticated."""
    model = config.models.main

    # Antigravity OAuth provider (no API key needed)
    ag = config.providers.antigravity
    if ag.enabled:
        from nanobot.providers.antigravity.auth import AntigravityAuthManager
        from nanobot.providers.antigravity.provider import AntigravityProvider

        auth = AntigravityAuthManager()
        if auth.is_authenticated:
            return AntigravityProvider(
                auth_manager=auth,
                endpoint=ag.endpoint or None,
                default_model=model,
            )
        else:
            console.print(
                "[yellow]Antigravity enabled but not authenticated. Run: nanobot auth login[/yellow]"
            )

    # Fallback to LiteLLM
    from nanobot.providers.litellm_provider import LiteLLMProvider

    p = config.get_provider()
    if not (p and p.api_key) and not model.startswith("bedrock/"):
        console.print("[red]Error: No API key configured.[/red]")
        console.print("Set one in ~/.nanobot/config.json under providers section")
        console.print("Or enable Antigravity: nanobot auth login")
        raise typer.Exit(1)
    return LiteLLMProvider(
        api_key=p.api_key if p else None,
        api_base=config.get_api_base(),
        default_model=model,
        extra_headers=p.extra_headers if p else None,
        provider_name=config.get_provider_name(),
    )


# ============================================================================
# Gateway / Server
# ============================================================================


@app.command()
def gateway(
    port: int = typer.Option(18790, "--port", "-p", help="Gateway port"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
):
    """Start the nanobot gateway."""
    from nanobot.config.loader import load_config, get_data_dir
    from nanobot.bus.queue import MessageBus
    from nanobot.agent.loop import AgentLoop
    from nanobot.channels.manager import ChannelManager
    from nanobot.session.manager import SessionManager
    from nanobot.cron.service import CronService
    from nanobot.cron.types import CronJob
    from nanobot.heartbeat.service import HeartbeatService

    if verbose:
        import logging

        logging.basicConfig(level=logging.DEBUG)

    console.print(f"{__logo__} Starting nanobot gateway on port {port}...")

    config = load_config()
    bus = MessageBus()
    provider = _make_provider(config)
    session_manager = SessionManager(config.workspace_path)

    # Create cron service first (callback set after agent creation)
    cron_store_path = get_data_dir() / "cron" / "jobs.json"
    cron = CronService(cron_store_path)

    # Create agent with cron service
    agent = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=config.workspace_path,
        model=config.models.main,
        agent_model=config.models.agent_model,
        max_iterations=config.agents.defaults.max_tool_iterations,
        memory_window=config.agents.defaults.memory_window,
        brave_api_key=config.tools.web.search.api_key or None,
        exec_config=config.tools.exec,
        cron_service=cron,
        restrict_to_workspace=config.tools.restrict_to_workspace,
        session_manager=session_manager,
    )

    # Set cron callback (needs agent)
    async def on_cron_job(job: CronJob) -> str | None:
        """Execute a cron job through the agent."""
        response = await agent.process_direct(
            job.payload.message,
            session_key=f"cron:{job.id}",
            channel=job.payload.channel or "cli",
            chat_id=job.payload.to or "direct",
        )
        if job.payload.deliver and job.payload.to:
            from nanobot.bus.events import OutboundMessage

            await bus.publish_outbound(
                OutboundMessage(
                    channel=job.payload.channel or "cli",
                    chat_id=job.payload.to,
                    content=response or "",
                )
            )
        return response

    cron.on_job = on_cron_job

    # Create heartbeat service
    async def on_heartbeat(prompt: str) -> str:
        """Execute heartbeat through the agent."""
        return await agent.process_direct(prompt, session_key="heartbeat")

    heartbeat = HeartbeatService(
        workspace=config.workspace_path,
        on_heartbeat=on_heartbeat,
        interval_s=30 * 60,  # 30 minutes
        enabled=True,
    )

    # Create channel manager
    channels = ChannelManager(config, bus)

    if channels.enabled_channels:
        console.print(f"[green]✓[/green] Channels enabled: {', '.join(channels.enabled_channels)}")
    else:
        console.print("[yellow]Warning: No channels enabled[/yellow]")

    cron_status = cron.status()
    if cron_status["jobs"] > 0:
        console.print(f"[green]✓[/green] Cron: {cron_status['jobs']} scheduled jobs")

    console.print(f"[green]✓[/green] Heartbeat: every 30m")

    async def run():
        try:
            await cron.start()
            await heartbeat.start()
            await asyncio.gather(
                agent.run(),
                channels.start_all(),
            )
        except KeyboardInterrupt:
            console.print("\nShutting down...")
            heartbeat.stop()
            cron.stop()
            agent.stop()
            await channels.stop_all()

    asyncio.run(run())


# ============================================================================
# Agent Commands
# ============================================================================


@app.command()
def agent(
    message: str = typer.Option(None, "--message", "-m", help="Message to send to the agent"),
    session_id: str = typer.Option("cli:direct", "--session", "-s", help="Session ID"),
    markdown: bool = typer.Option(
        True, "--markdown/--no-markdown", help="Render assistant output as Markdown"
    ),
    logs: bool = typer.Option(
        False, "--logs/--no-logs", help="Show nanobot runtime logs during chat"
    ),
):
    """Interact with the agent directly."""
    from nanobot.config.loader import load_config
    from nanobot.bus.queue import MessageBus
    from nanobot.agent.loop import AgentLoop
    from loguru import logger

    config = load_config()

    bus = MessageBus()
    provider = _make_provider(config)

    if logs:
        logger.enable("nanobot")
    else:
        logger.disable("nanobot")

    agent_loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=config.workspace_path,
        model=config.models.main,
        agent_model=config.models.agent_model,
        max_iterations=config.agents.defaults.max_tool_iterations,
        memory_window=config.agents.defaults.memory_window,
        brave_api_key=config.tools.web.search.api_key or None,
        exec_config=config.tools.exec,
        restrict_to_workspace=config.tools.restrict_to_workspace,
    )

    # Show spinner when logs are off (no output to miss); skip when logs are on
    def _thinking_ctx():
        if logs:
            from contextlib import nullcontext

            return nullcontext()
        # Animated spinner is safe to use with prompt_toolkit input handling
        return console.status("[dim]nanobot is thinking...[/dim]", spinner="dots")

    if message:
        # Single message mode
        async def run_once():
            with _thinking_ctx():
                response = await agent_loop.process_direct(message, session_id)
            _print_agent_response(response, render_markdown=markdown)

        asyncio.run(run_once())
    else:
        # Interactive mode
        _init_prompt_session()
        console.print(
            f"{__logo__} Interactive mode (type [bold]exit[/bold] or [bold]Ctrl+C[/bold] to quit)\n"
        )

        def _exit_on_sigint(signum, frame):
            _restore_terminal()
            console.print("\nGoodbye!")
            os._exit(0)

        signal.signal(signal.SIGINT, _exit_on_sigint)

        async def run_interactive():
            while True:
                try:
                    _flush_pending_tty_input()
                    user_input = await _read_interactive_input_async()
                    command = user_input.strip()
                    if not command:
                        continue

                    if _is_exit_command(command):
                        _restore_terminal()
                        console.print("\nGoodbye!")
                        break

                    with _thinking_ctx():
                        response = await agent_loop.process_direct(user_input, session_id)
                    _print_agent_response(response, render_markdown=markdown)
                except KeyboardInterrupt:
                    _restore_terminal()
                    console.print("\nGoodbye!")
                    break
                except EOFError:
                    _restore_terminal()
                    console.print("\nGoodbye!")
                    break

        asyncio.run(run_interactive())


# ============================================================================
# Channel Commands
# ============================================================================


channels_app = typer.Typer(help="Manage channels")
app.add_typer(channels_app, name="channels")


@channels_app.command("status")
def channels_status():
    """Show channel status."""
    from nanobot.config.loader import load_config

    config = load_config()

    table = Table(title="Channel Status")
    table.add_column("Channel", style="cyan")
    table.add_column("Enabled", style="green")
    table.add_column("Configuration", style="yellow")

    # WhatsApp
    wa = config.channels.whatsapp
    table.add_row("WhatsApp", "✓" if wa.enabled else "✗", wa.bridge_url)

    dc = config.channels.discord
    table.add_row("Discord", "✓" if dc.enabled else "✗", dc.gateway_url)

    # Feishu
    fs = config.channels.feishu
    fs_config = f"app_id: {fs.app_id[:10]}..." if fs.app_id else "[dim]not configured[/dim]"
    table.add_row("Feishu", "✓" if fs.enabled else "✗", fs_config)

    # Mochat
    mc = config.channels.mochat
    mc_base = mc.base_url or "[dim]not configured[/dim]"
    table.add_row("Mochat", "✓" if mc.enabled else "✗", mc_base)

    # Telegram
    tg = config.channels.telegram
    tg_config = f"token: {tg.token[:10]}..." if tg.token else "[dim]not configured[/dim]"
    table.add_row("Telegram", "✓" if tg.enabled else "✗", tg_config)

    # Slack
    slack = config.channels.slack
    slack_config = "socket" if slack.app_token and slack.bot_token else "[dim]not configured[/dim]"
    table.add_row("Slack", "✓" if slack.enabled else "✗", slack_config)

    console.print(table)


def _get_bridge_dir() -> Path:
    """Get the bridge directory, setting it up if needed."""
    import shutil
    import subprocess

    # User's bridge location
    user_bridge = Path.home() / ".nanobot" / "bridge"

    # Check if already built
    if (user_bridge / "dist" / "index.js").exists():
        return user_bridge

    # Check for npm
    if not shutil.which("npm"):
        console.print("[red]npm not found. Please install Node.js >= 18.[/red]")
        raise typer.Exit(1)

    # Find source bridge: first check package data, then source dir
    pkg_bridge = Path(__file__).parent.parent / "bridge"  # nanobot/bridge (installed)
    src_bridge = Path(__file__).parent.parent.parent / "bridge"  # repo root/bridge (dev)

    source = None
    if (pkg_bridge / "package.json").exists():
        source = pkg_bridge
    elif (src_bridge / "package.json").exists():
        source = src_bridge

    if not source:
        console.print("[red]Bridge source not found.[/red]")
        console.print("Try reinstalling: pip install --force-reinstall nanobot")
        raise typer.Exit(1)

    console.print(f"{__logo__} Setting up bridge...")

    # Copy to user directory
    user_bridge.parent.mkdir(parents=True, exist_ok=True)
    if user_bridge.exists():
        shutil.rmtree(user_bridge)
    shutil.copytree(source, user_bridge, ignore=shutil.ignore_patterns("node_modules", "dist"))

    # Install and build
    try:
        console.print("  Installing dependencies...")
        subprocess.run(["npm", "install"], cwd=user_bridge, check=True, capture_output=True)

        console.print("  Building...")
        subprocess.run(["npm", "run", "build"], cwd=user_bridge, check=True, capture_output=True)

        console.print("[green]✓[/green] Bridge ready\n")
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Build failed: {e}[/red]")
        if e.stderr:
            console.print(f"[dim]{e.stderr.decode()[:500]}[/dim]")
        raise typer.Exit(1)

    return user_bridge


@channels_app.command("login")
def channels_login():
    """Link device via QR code."""
    import subprocess
    from nanobot.config.loader import load_config

    config = load_config()
    bridge_dir = _get_bridge_dir()

    console.print(f"{__logo__} Starting bridge...")
    console.print("Scan the QR code to connect.\n")

    env = {**os.environ}
    if config.channels.whatsapp.bridge_token:
        env["BRIDGE_TOKEN"] = config.channels.whatsapp.bridge_token

    try:
        subprocess.run(["npm", "start"], cwd=bridge_dir, check=True, env=env)
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Bridge failed: {e}[/red]")
    except FileNotFoundError:
        console.print("[red]npm not found. Please install Node.js.[/red]")


# ============================================================================
# Cron Commands
# ============================================================================

cron_app = typer.Typer(help="Manage scheduled tasks")
app.add_typer(cron_app, name="cron")


@cron_app.command("list")
def cron_list(
    all: bool = typer.Option(False, "--all", "-a", help="Include disabled jobs"),
):
    """List scheduled jobs."""
    from nanobot.config.loader import get_data_dir
    from nanobot.cron.service import CronService

    store_path = get_data_dir() / "cron" / "jobs.json"
    service = CronService(store_path)

    jobs = service.list_jobs(include_disabled=all)

    if not jobs:
        console.print("No scheduled jobs.")
        return

    table = Table(title="Scheduled Jobs")
    table.add_column("ID", style="cyan")
    table.add_column("Name")
    table.add_column("Schedule")
    table.add_column("Status")
    table.add_column("Next Run")

    import time

    for job in jobs:
        # Format schedule
        if job.schedule.kind == "every":
            sched = f"every {(job.schedule.every_ms or 0) // 1000}s"
        elif job.schedule.kind == "cron":
            sched = job.schedule.expr or ""
        else:
            sched = "one-time"

        # Format next run
        next_run = ""
        if job.state.next_run_at_ms:
            next_time = time.strftime(
                "%Y-%m-%d %H:%M", time.localtime(job.state.next_run_at_ms / 1000)
            )
            next_run = next_time

        status = "[green]enabled[/green]" if job.enabled else "[dim]disabled[/dim]"

        table.add_row(job.id, job.name, sched, status, next_run)

    console.print(table)


@cron_app.command("add")
def cron_add(
    name: str = typer.Option(..., "--name", "-n", help="Job name"),
    message: str = typer.Option(..., "--message", "-m", help="Message for agent"),
    every: int = typer.Option(None, "--every", "-e", help="Run every N seconds"),
    cron_expr: str = typer.Option(None, "--cron", "-c", help="Cron expression (e.g. '0 9 * * *')"),
    at: str = typer.Option(None, "--at", help="Run once at time (ISO format)"),
    deliver: bool = typer.Option(False, "--deliver", "-d", help="Deliver response to channel"),
    to: str = typer.Option(None, "--to", help="Recipient for delivery"),
    channel: str = typer.Option(
        None, "--channel", help="Channel for delivery (e.g. 'telegram', 'whatsapp')"
    ),
):
    """Add a scheduled job."""
    from nanobot.config.loader import get_data_dir
    from nanobot.cron.service import CronService
    from nanobot.cron.types import CronSchedule

    # Determine schedule type
    if every:
        schedule = CronSchedule(kind="every", every_ms=every * 1000)
    elif cron_expr:
        schedule = CronSchedule(kind="cron", expr=cron_expr)
    elif at:
        import datetime

        dt = datetime.datetime.fromisoformat(at)
        schedule = CronSchedule(kind="at", at_ms=int(dt.timestamp() * 1000))
    else:
        console.print("[red]Error: Must specify --every, --cron, or --at[/red]")
        raise typer.Exit(1)

    store_path = get_data_dir() / "cron" / "jobs.json"
    service = CronService(store_path)

    job = service.add_job(
        name=name,
        schedule=schedule,
        message=message,
        deliver=deliver,
        to=to,
        channel=channel,
    )

    console.print(f"[green]✓[/green] Added job '{job.name}' ({job.id})")


@cron_app.command("remove")
def cron_remove(
    job_id: str = typer.Argument(..., help="Job ID to remove"),
):
    """Remove a scheduled job."""
    from nanobot.config.loader import get_data_dir
    from nanobot.cron.service import CronService

    store_path = get_data_dir() / "cron" / "jobs.json"
    service = CronService(store_path)

    if service.remove_job(job_id):
        console.print(f"[green]✓[/green] Removed job {job_id}")
    else:
        console.print(f"[red]Job {job_id} not found[/red]")


@cron_app.command("enable")
def cron_enable(
    job_id: str = typer.Argument(..., help="Job ID"),
    disable: bool = typer.Option(False, "--disable", help="Disable instead of enable"),
):
    """Enable or disable a job."""
    from nanobot.config.loader import get_data_dir
    from nanobot.cron.service import CronService

    store_path = get_data_dir() / "cron" / "jobs.json"
    service = CronService(store_path)

    job = service.enable_job(job_id, enabled=not disable)
    if job:
        status = "disabled" if disable else "enabled"
        console.print(f"[green]✓[/green] Job '{job.name}' {status}")
    else:
        console.print(f"[red]Job {job_id} not found[/red]")


@cron_app.command("run")
def cron_run(
    job_id: str = typer.Argument(..., help="Job ID to run"),
    force: bool = typer.Option(False, "--force", "-f", help="Run even if disabled"),
):
    """Manually run a job."""
    from nanobot.config.loader import get_data_dir
    from nanobot.cron.service import CronService

    store_path = get_data_dir() / "cron" / "jobs.json"
    service = CronService(store_path)

    async def run():
        return await service.run_job(job_id, force=force)

    if asyncio.run(run()):
        console.print(f"[green]✓[/green] Job executed")
    else:
        console.print(f"[red]Failed to run job {job_id}[/red]")


# ============================================================================
# Status Commands
# ============================================================================


@app.command()
def status():
    """Show nanobot status."""
    from nanobot.config.loader import load_config, get_config_path

    config_path = get_config_path()
    config = load_config()
    workspace = config.workspace_path

    console.print(f"{__logo__} nanobot Status\n")

    console.print(
        f"Config: {config_path} {'[green]✓[/green]' if config_path.exists() else '[red]✗[/red]'}"
    )
    console.print(
        f"Workspace: {workspace} {'[green]✓[/green]' if workspace.exists() else '[red]✗[/red]'}"
    )

    if config_path.exists():
        from nanobot.providers.registry import PROVIDERS

        console.print(f"Model (main): {config.models.main}")
        if config.models.agent:
            console.print(f"Model (agent): {config.models.agent}")

        # Antigravity status
        ag = config.providers.antigravity
        if ag.enabled:
            from nanobot.providers.antigravity.auth import AntigravityAuthManager

            auth = AntigravityAuthManager()
            if auth.is_authenticated:
                console.print(f"Antigravity: [green]✓ {auth.email}[/green]")
            else:
                console.print("Antigravity: [yellow]enabled but not authenticated[/yellow]")
        else:
            console.print("Antigravity: [dim]not enabled[/dim]")

        # Check API keys from registry
        for spec in PROVIDERS:
            p = getattr(config.providers, spec.name, None)
            if p is None:
                continue
            if spec.is_local:
                # Local deployments show api_base instead of api_key
                if p.api_base:
                    console.print(f"{spec.label}: [green]✓ {p.api_base}[/green]")
                else:
                    console.print(f"{spec.label}: [dim]not set[/dim]")
            else:
                has_key = bool(p.api_key)
                console.print(
                    f"{spec.label}: {'[green]✓[/green]' if has_key else '[dim]not set[/dim]'}"
                )


# ============================================================================
# Auth Commands (Antigravity OAuth)
# ============================================================================


auth_app = typer.Typer(help="Manage Antigravity OAuth authentication")
app.add_typer(auth_app, name="auth")


@auth_app.command("login")
def auth_login():
    """Authenticate with Google via Antigravity OAuth."""
    from nanobot.providers.antigravity.auth import AntigravityAuthManager
    from nanobot.config.loader import load_config, save_config

    console.print(f"{__logo__} Antigravity OAuth Login")
    console.print("Opening browser for Google sign-in...\n")

    auth = AntigravityAuthManager()

    try:
        creds = auth.login()
        console.print(f"[green]✓[/green] Authenticated as [cyan]{creds.email}[/cyan]")

        # Show how many accounts are stored
        if len(auth.accounts) > 1:
            console.print(
                f"[dim]  ({len(auth.accounts)} accounts stored, active: {creds.email})[/dim]"
            )

        # Auto-enable antigravity in config
        config = load_config()
        if not config.providers.antigravity.enabled:
            config.providers.antigravity.enabled = True
            save_config(config)
            console.print("[green]✓[/green] Antigravity provider enabled in config")

        console.print(f"\nAvailable models:")
        from nanobot.providers.antigravity.constants import MODELS

        for m in MODELS:
            console.print(f"  • {m}")
        console.print(f"\nSet your model in config: [cyan]models.main[/cyan]")

    except Exception as e:
        console.print(f"[red]Login failed: {e}[/red]")
        raise typer.Exit(1)


@auth_app.command("status")
def auth_status():
    """Show Antigravity authentication status."""
    from nanobot.providers.antigravity.auth import AntigravityAuthManager

    auth = AntigravityAuthManager()

    if not auth.accounts:
        console.print("[yellow]Not authenticated[/yellow]")
        console.print("Run: [cyan]nanobot auth login[/cyan]")
        return

    for acct_email in auth.accounts:
        marker = " [green](active)[/green]" if acct_email == auth.email else ""
        console.print(f"  [cyan]{acct_email}[/cyan]{marker}")


@auth_app.command("list")
def auth_list():
    """List all stored Antigravity accounts."""
    from nanobot.providers.antigravity.auth import AntigravityAuthManager

    auth = AntigravityAuthManager()

    if not auth.accounts:
        console.print("[yellow]No accounts stored.[/yellow]")
        console.print("Run: [cyan]nanobot auth login[/cyan]")
        return

    table = Table(title="Antigravity Accounts")
    table.add_column("Email", style="cyan")
    table.add_column("Active", style="green")

    for acct_email in auth.accounts:
        active = "✓" if acct_email == auth.email else ""
        table.add_row(acct_email, active)

    console.print(table)


@auth_app.command("switch")
def auth_switch(
    email: str = typer.Argument(..., help="Email of the account to switch to"),
):
    """Switch the active Antigravity account."""
    from nanobot.providers.antigravity.auth import AntigravityAuthManager

    auth = AntigravityAuthManager()

    if auth.switch(email):
        console.print(f"[green]✓[/green] Switched to [cyan]{email}[/cyan]")
    else:
        console.print(f"[red]Account {email} not found.[/red]")
        if auth.accounts:
            console.print("Available accounts:")
            for acct_email in auth.accounts:
                console.print(f"  • {acct_email}")


@auth_app.command("logout")
def auth_logout(
    email: str = typer.Option(None, "--email", "-e", help="Specific account to remove"),
    all_accounts: bool = typer.Option(False, "--all", "-a", help="Remove all accounts"),
):
    """Remove stored Antigravity credentials."""
    from nanobot.providers.antigravity.auth import AntigravityAuthManager

    auth = AntigravityAuthManager()

    if all_accounts:
        auth.logout("*")
        console.print("[green]✓[/green] All credentials removed")
    elif email:
        auth.logout(email)
        console.print(f"[green]✓[/green] Credentials for {email} removed")
        if auth.is_authenticated:
            console.print(f"[dim]  Active account: {auth.email}[/dim]")
    else:
        removed = auth.email or "(none)"
        auth.logout()
        console.print(f"[green]✓[/green] Credentials for {removed} removed")
        if auth.is_authenticated:
            console.print(f"[dim]  Switched to: {auth.email}[/dim]")


@app.command()
def hello(name: str = typer.Option(..., help="Name to greet")):
    """Greet the user."""
    console.print(f"Hello, {name}! Welcome to the code.")


# ============================================================================
# Metrics Commands
# ============================================================================


metrics_app = typer.Typer(help="View agent metrics and observability data")
app.add_typer(metrics_app, name="metrics")


@metrics_app.command("summary")
def metrics_summary(
    hours: float = typer.Option(24, "--hours", "-h", help="Look-back window in hours"),
):
    """Show high-level metrics summary."""
    from nanobot.metrics.collector import MetricsCollector
    from nanobot.metrics.report import summary_report

    collector = MetricsCollector()
    report = summary_report(collector, hours=hours)

    console.print(f"\n{__logo__} Metrics Summary (last {report['period_hours']}h)\n")

    ov = report["overview"]
    table = Table(title="Overview")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")
    table.add_row("Sessions", str(ov["total_sessions"]))
    table.add_row("Success rate", f"{ov['success_rate']}%")
    table.add_row("Avg iterations/session", str(ov["avg_iterations_per_session"]))
    table.add_row("LLM calls", str(report["llm_calls"]))
    console.print(table)

    tok = report["tokens"]
    table2 = Table(title="Tokens")
    table2.add_column("Metric", style="cyan")
    table2.add_column("Value", justify="right")
    table2.add_row("Total prompt", f"{tok['total_prompt']:,}")
    table2.add_row("Total completion", f"{tok['total_completion']:,}")
    table2.add_row("Total", f"{tok['total']:,}")
    table2.add_row("Avg per session", f"{tok['avg_per_session']:,}")
    table2.add_row("Per success", f"{tok['per_success']:,}")
    console.print(table2)

    tl = report["tools"]
    table3 = Table(title="Tools")
    table3.add_column("Metric", style="cyan")
    table3.add_column("Value", justify="right")
    table3.add_row("Total calls", str(tl["total_calls"]))
    table3.add_row("Success rate", f"{tl['success_rate']}%")
    console.print(table3)
    console.print()


@metrics_app.command("tools")
def metrics_tools(
    hours: float = typer.Option(24, "--hours", "-h", help="Look-back window in hours"),
):
    """Show per-tool metrics breakdown."""
    from nanobot.metrics.collector import MetricsCollector
    from nanobot.metrics.report import tool_report

    collector = MetricsCollector()
    rows = tool_report(collector, hours=hours)

    if not rows:
        console.print("[yellow]No tool events recorded yet.[/yellow]")
        return

    console.print(f"\n{__logo__} Tool Metrics (last {hours}h)\n")

    table = Table()
    table.add_column("Tool", style="cyan")
    table.add_column("Calls", justify="right")
    table.add_column("Success %", justify="right")
    table.add_column("Avg Latency", justify="right")
    table.add_column("Avg In", justify="right")
    table.add_column("Avg Out", justify="right")
    table.add_column("Top Errors", style="red")

    for r in rows:
        errors = (
            ", ".join(f"{k}({v})" for k, v in r["top_errors"].items()) if r["top_errors"] else ""
        )
        table.add_row(
            r["tool"],
            str(r["calls"]),
            f"{r['success_rate']}%",
            f"{r['avg_latency_ms']}ms",
            str(r["avg_input_size"]),
            str(r["avg_output_size"]),
            errors[:60] if errors else "[dim]-[/dim]",
        )

    console.print(table)
    console.print()


@metrics_app.command("sessions")
def metrics_sessions(
    last: int = typer.Option(20, "--last", "-n", help="Number of recent sessions"),
):
    """Show recent session summaries."""
    from nanobot.metrics.collector import MetricsCollector
    from nanobot.metrics.report import session_report

    collector = MetricsCollector()
    rows = session_report(collector, last_n=last)

    if not rows:
        console.print("[yellow]No sessions recorded yet.[/yellow]")
        return

    console.print(f"\n{__logo__} Recent Sessions (last {last})\n")

    table = Table()
    table.add_column("Session", style="cyan", max_width=30)
    table.add_column("Time", max_width=16)
    table.add_column("OK", justify="center")
    table.add_column("Iter", justify="right")
    table.add_column("Tools", justify="right")
    table.add_column("Tokens", justify="right")
    table.add_column("Duration", justify="right")
    table.add_column("Model", style="dim", max_width=20)

    for r in rows:
        started = r["started_at"][:16] if r["started_at"] != "?" else "?"
        ok = "[green]✓[/green]" if r["success"] else "[red]✗[/red]"
        dur = f"{r['duration_ms']}ms" if r["duration_ms"] else "?"
        table.add_row(
            r["session_id"],
            started,
            ok,
            str(r["iterations"]),
            str(r["tool_calls"]),
            f"{r['total_tokens']:,}",
            dur,
            r["model"],
        )

    console.print(table)
    console.print()


@metrics_app.command("models")
def metrics_models(
    hours: float = typer.Option(
        168, "--hours", "-h", help="Look-back window in hours (default: 7 days)"
    ),
):
    """Compare model efficiency and success rates."""
    from nanobot.metrics.collector import MetricsCollector
    from nanobot.metrics.report import model_report

    collector = MetricsCollector()
    rows = model_report(collector, hours=hours)

    if not rows:
        console.print("[yellow]No session data recorded yet.[/yellow]")
        return

    console.print(f"\n{__logo__} Model Comparison (last {hours}h)\n")

    table = Table()
    table.add_column("Model", style="cyan")
    table.add_column("Sessions", justify="right")
    table.add_column("Success %", justify="right")
    table.add_column("Total Tokens", justify="right")
    table.add_column("Tokens/Session", justify="right")
    table.add_column("Tokens/Success", justify="right")

    for r in rows:
        table.add_row(
            r["model"],
            str(r["sessions"]),
            f"{r['success_rate']}%",
            f"{r['total_tokens']:,}",
            f"{r['tokens_per_session']:,}",
            f"{r['tokens_per_success']:,}",
        )

    console.print(table)
    console.print()


@metrics_app.command("reset")
def metrics_reset(
    confirm: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Clear all collected metrics data."""
    from nanobot.metrics.collector import MetricsCollector

    collector = MetricsCollector()
    metrics_dir = collector.metrics_dir

    if not confirm:
        if not typer.confirm(f"Delete all metrics in {metrics_dir}?"):
            raise typer.Exit()

    import shutil

    if metrics_dir.exists():
        shutil.rmtree(metrics_dir)
        console.print("[green]✓[/green] Metrics data cleared")
    else:
        console.print("[dim]No metrics data found[/dim]")


if __name__ == "__main__":
    app()
