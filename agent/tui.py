"""
Layla TUI — Textual-based terminal interface.

Usage:
    cd agent && python tui.py

Commands (type in input bar):
    /aspect <name>     Switch active aspect
    /think             Toggle deliberation display
    /study <topic>     Add a study plan topic
    /approve <uuid>    Approve a pending tool call
    /wakeup            Trigger session greeting
    /voice             Record from mic, transcribe, send to agent (voice-to-code)
    /undo              Revert last Layla auto-commit (git revert HEAD)
    /add <path>        Add file to context for next message
    /run <cmd>         Execute command (no shell; compound commands like && not supported)
    /diff              Show git diff (uncommitted changes)
    /export            Dump system state to layla_export.json
"""
import asyncio
import struct
from pathlib import Path

import httpx
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.widgets import Footer, Header, Input, Log, Static

BASE_URL = "http://localhost:8000"

ASPECTS = [
    ("morrigan",  "⚔  Morrigan"),
    ("nyx",       "✦  Nyx"),
    ("echo",      "◎  Echo"),
    ("eris",      "⚡  Eris"),
    ("cassandra", "⌖  Cassandra"),
    ("lilith",    "⊛  Lilith"),
]

ASPECT_COLORS = {
    "morrigan":  "dark_red",
    "nyx":       "dark_magenta",
    "echo":      "purple",
    "eris":      "red",
    "cassandra": "dark_blue",
    "lilith":    "bright_red",
}


class LaylaApp(App):
    CSS = """
    Screen {
        background: #0a0008;
    }
    Header {
        background: #100010;
        color: #8b0000;
    }
    Footer {
        background: #100010;
        color: #7a6a8a;
    }
    #layout {
        layout: horizontal;
        height: 1fr;
    }
    #sidebar {
        width: 22;
        border-right: solid #3d0050;
        background: #100010;
        padding: 1 1;
    }
    #main-col {
        layout: vertical;
        width: 1fr;
    }
    #chat-scroll {
        height: 1fr;
        border: solid #3d0050;
        padding: 1 2;
    }
    #chat-log {
        height: auto;
    }
    #input-row {
        height: 3;
        layout: horizontal;
        padding: 0 1;
        border-top: solid #3d0050;
        background: #100010;
    }
    #msg-input {
        width: 1fr;
        border: solid #3d0050;
        background: #1a001a;
        color: #d4c5e2;
    }
    #panels {
        width: 26;
        border-left: solid #3d0050;
        background: #100010;
        padding: 1 1;
    }
    .section-title {
        color: #7a6a8a;
        text-style: bold;
    }
    .aspect-item {
        color: #d4c5e2;
        padding: 0 1;
    }
    .aspect-item.active {
        color: #8b0000;
        text-style: bold;
    }
    .msg-you {
        color: #7ecfff;
    }
    .msg-layla {
        color: #c6a0f0;
    }
    .msg-system {
        color: #7a6a8a;
        text-style: italic;
    }
    .greeting {
        color: #8b0000;
        text-style: italic;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit"),
        Binding("ctrl+t", "toggle_thinking", "Toggle thinking"),
        Binding("ctrl+w", "do_wakeup", "Wakeup"),
    ]

    def __init__(self):
        super().__init__()
        self._aspect = "morrigan"
        self._show_thinking = False
        self._allow_write = False
        self._allow_run = False
        self._pending: list = []
        self._study_plans: list = []
        self._context_files: list = []  # /add: paths for next message
        self._run_output: str = ""  # /run: output to inject into next message

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="layout"):
            with Vertical(id="sidebar"):
                yield Static("∴ ASPECTS", classes="section-title")
                for aid, label in ASPECTS:
                    item = Static(label, classes="aspect-item" + (" active" if aid == self._aspect else ""))
                    item.id = f"asp-{aid}"
                    yield item
                yield Static("")
                yield Static("∴ OPTIONS", classes="section-title")
                yield Static("[think: OFF]", id="think-status")
            with Vertical(id="main-col"):
                with ScrollableContainer(id="chat-scroll"):
                    yield Log(id="chat-log", highlight=True)
                with Horizontal(id="input-row"):
                    yield Input(placeholder="Speak to Layla…  (/aspect /think /add /run /diff /undo /voice /export)", id="msg-input")
            with Vertical(id="panels"):
                yield Static("∴ PENDING", classes="section-title")
                yield Static("none", id="pending-list")
                yield Static("")
                yield Static("∴ STUDY PLANS", classes="section-title")
                yield Static("none", id="study-list")
        yield Footer()

    def on_mount(self) -> None:
        self.call_after_refresh(self._do_wakeup)
        self.call_after_refresh(self._refresh_panels)
        self.query_one("#msg-input", Input).focus()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        event.input.value = ""

        if text.startswith("/"):
            await self._handle_command(text)
            return

        log = self.query_one("#chat-log", Log)
        # Prepend context from /add and /run
        ctx_parts = []
        if self._run_output:
            ctx_parts.append(f"[Command output:\n{self._run_output}]")
            self._run_output = ""
        if self._context_files:
            for p in self._context_files:
                try:
                    content = Path(p).expanduser().resolve().read_text(encoding="utf-8", errors="replace")[:6000]
                    ctx_parts.append(f"[File {p}:\n{content}]")
                except Exception:
                    ctx_parts.append(f"[File {p}: (could not read)]")
            self._context_files = []
        full_msg = ("\n\n".join(ctx_parts) + "\n\n" + text).strip() if ctx_parts else text
        log.write_line(f"[bold cyan]USER:[/] {text}")
        log.write_line("─── ✦ ───")

        try:
            resp = httpx.post(
                f"{BASE_URL}/agent",
                json={
                    "message": full_msg,
                    "aspect_id": self._aspect,
                    "show_thinking": self._show_thinking,
                    "allow_write": self._allow_write,
                    "allow_run": self._allow_run,
                },
                timeout=60,
            )
            data = resp.json()
            response = data.get("response", "")
            aspect_name = data.get("aspect_name", "Layla")
            log.write_line(f"[bold magenta]∴ {aspect_name.upper()}:[/] {response}")
        except Exception as e:
            log.write_line(f"[bold red]ERROR:[/] {e}")

        await self._refresh_panels()

    async def _handle_command(self, text: str) -> None:
        log = self.query_one("#chat-log", Log)
        parts = text.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        if cmd == "/aspect":
            if not arg:
                log.write_line("[yellow]Usage: /aspect <name>[/]")
                return
            aid = arg.lower()
            self._set_aspect(aid)
            log.write_line(f"[bold]Aspect set: {aid.upper()}[/]")

        elif cmd == "/think":
            self._show_thinking = not self._show_thinking
            status = "ON" if self._show_thinking else "OFF"
            self.query_one("#think-status", Static).update(f"[think: {status}]")
            log.write_line(f"[yellow]Deliberation: {status}[/]")

        elif cmd == "/study":
            if not arg:
                log.write_line("[yellow]Usage: /study <topic>[/]")
                return
            try:
                httpx.post(f"{BASE_URL}/study_plans", json={"topic": arg}, timeout=10)
                log.write_line(f"[green]Study plan added: {arg}[/]")
            except Exception as e:
                log.write_line(f"[red]Error: {e}[/]")
            await self._refresh_panels()

        elif cmd == "/approve":
            if not arg:
                log.write_line("[yellow]Usage: /approve <uuid>[/]")
                return
            try:
                resp = httpx.post(f"{BASE_URL}/approve", json={"id": arg}, timeout=10)
                data = resp.json()
                log.write_line(f"[green]Approved {arg}: {data}[/]")
            except Exception as e:
                log.write_line(f"[red]Error: {e}[/]")
            await self._refresh_panels()

        elif cmd == "/wakeup":
            await self._do_wakeup()

        elif cmd == "/export":
            try:
                resp = httpx.get(f"{BASE_URL}/system_export", timeout=10)
                out = Path("layla_export.json")
                out.write_text(resp.text, encoding="utf-8")
                log.write_line(f"[green]Exported to {out.resolve()}[/]")
            except Exception as e:
                log.write_line(f"[red]Export error: {e}[/]")

        elif cmd == "/write":
            self._allow_write = not self._allow_write
            log.write_line(f"[yellow]Allow Write: {'ON' if self._allow_write else 'OFF'}[/]")

        elif cmd == "/allow-run":
            self._allow_run = not self._allow_run
            log.write_line(f"[yellow]Allow Run: {'ON' if self._allow_run else 'OFF'}[/]")

        elif cmd == "/add":
            if not arg:
                log.write_line("[yellow]Usage: /add <path> — add file to context for next message[/]")
                return
            p = Path(arg).expanduser().resolve()
            if not p.exists():
                log.write_line(f"[red]File not found: {p}[/]")
                return
            self._context_files.append(str(p))
            log.write_line(f"[green]Added {p.name} to context ({len(self._context_files)} file(s))[/]")

        elif cmd == "/run":
            if not arg:
                self._allow_run = not self._allow_run
                log.write_line(f"[yellow]Allow Run: {'ON' if self._allow_run else 'OFF'}[/]")
                return
            log.write_line(f"[yellow]Running: {arg}[/]")
            try:
                import shlex
                import subprocess
                argv = shlex.split(arg)
                if not argv:
                    log.write_line("[red]Empty command[/]")
                    return
                r = subprocess.run(
                    argv,
                    shell=False,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    cwd=str(Path.cwd()),
                )
                out = (r.stdout or "") + (r.stderr or "")
                self._run_output = out[:4000] or "(no output)"
                log.write_line(f"[green]Output captured for next message ({len(self._run_output)} chars)[/]")
            except subprocess.TimeoutExpired:
                self._run_output = "(command timed out)"
                log.write_line("[red]Command timed out[/]")
            except Exception as e:
                log.write_line(f"[red]Run error: {e}[/]")

        elif cmd == "/diff":
            try:
                import subprocess
                r = subprocess.run(
                    ["git", "diff"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    cwd=str(Path.cwd()),
                )
                out = (r.stdout or r.stderr or "(no diff)")[:3000]
                log.write_line(f"[bold]Git diff:[/]\n{out}")
            except Exception as e:
                log.write_line(f"[red]Diff error: {e}[/]")

        elif cmd == "/voice":
            await self._do_voice(log)

        elif cmd == "/undo":
            try:
                resp = httpx.post(f"{BASE_URL}/undo", json={}, timeout=10)
                data = resp.json()
                if data.get("ok"):
                    log.write_line("[green]Reverted last Layla commit.[/]")
                else:
                    log.write_line(f"[red]{data.get('error', 'Undo failed')}[/]")
            except Exception as e:
                log.write_line(f"[red]Undo error: {e}[/]")

        else:
            log.write_line(f"[red]Unknown command: {cmd}[/]")

    def _record_voice(self) -> bytes:
        """Blocking: record 5s from mic, return WAV bytes."""
        import sounddevice as sd
        sample_rate = 16000
        duration_sec = 5
        rec = sd.rec(
            int(duration_sec * sample_rate),
            samplerate=sample_rate,
            channels=1,
            dtype="int16",
        )
        return self._raw_to_wav(rec, sample_rate)

    async def _do_voice(self, log) -> None:
        """Record from mic, transcribe, send to agent (voice-to-code)."""
        log.write_line("[yellow]Recording 5s from mic…[/]")
        try:
            wav_bytes = await asyncio.to_thread(self._record_voice)
            log.write_line("[yellow]Transcribing…[/]")
            resp = httpx.post(
                f"{BASE_URL}/voice/transcribe",
                content=wav_bytes,
                timeout=30,
            )
            data = resp.json()
            text = (data.get("text") or "").strip()
            if not text:
                log.write_line("[red]No speech detected.[/]")
                return
            log.write_line(f"[bold cyan]USER (voice):[/] {text}")
            log.write_line("─── ✦ ───")
            agent_resp = httpx.post(
                f"{BASE_URL}/agent",
                json={
                    "message": text,
                    "aspect_id": self._aspect,
                    "show_thinking": self._show_thinking,
                    "allow_write": self._allow_write,
                    "allow_run": self._allow_run,
                },
                timeout=60,
            )
            agent_data = agent_resp.json()
            log.write_line(f"[bold magenta]∴ {agent_data.get('aspect_name', 'Layla').upper()}:[/] {agent_data.get('response', '')}")
            await self._refresh_panels()
        except ImportError:
            log.write_line("[red]Voice requires: pip install sounddevice[/]")
        except Exception as e:
            log.write_line(f"[red]Voice error: {e}[/]")

    def _raw_to_wav(self, samples, sample_rate: int) -> bytes:
        """Convert int16 numpy array to WAV bytes."""
        import numpy as np
        buf = samples.astype(np.int16).tobytes()
        n = len(buf)
        header = struct.pack(
            "<4sI4s4sIHHIIHH4sI",
            b"RIFF", 36 + n, b"WAVE", b"fmt ", 16,
            1, 1, sample_rate, sample_rate * 2, 2, 16, b"data", n,
        )
        return header + buf

    def _set_aspect(self, aspect_id: str) -> None:
        for aid, _ in ASPECTS:
            widget = self.query_one(f"#asp-{aid}", Static)
            if aid == aspect_id:
                widget.add_class("active")
            else:
                widget.remove_class("active")
        self._aspect = aspect_id

    async def _do_wakeup(self) -> None:
        log = self.query_one("#chat-log", Log)
        try:
            resp = httpx.get(f"{BASE_URL}/wakeup", timeout=60)
            data = resp.json()
            greeting = data.get("greeting", "")
            if greeting:
                log.write_line(f"[bold red]∴ ECHO (SESSION START):[/] {greeting}")
                log.write_line("─── ✦ ───")
            await self._refresh_panels()
        except Exception:
            log.write_line("[dim]Server not reachable — start the agent first.[/]")

    async def _refresh_panels(self) -> None:
        try:
            resp = httpx.get(f"{BASE_URL}/pending", timeout=5)
            pending = [e for e in resp.json().get("pending", []) if e.get("status") == "pending"]
            if pending:
                lines = "\n".join(f"{e['tool']} [{e['id'][:8]}]" for e in pending)
                self.query_one("#pending-list", Static).update(lines)
            else:
                self.query_one("#pending-list", Static).update("none")
        except Exception:
            pass

        try:
            resp = httpx.get(f"{BASE_URL}/study_plans", timeout=5)
            plans = [p for p in resp.json().get("plans", []) if p.get("status") == "active"]
            if plans:
                lines = []
                for p in plans[:6]:
                    t = (p.get("topic") or "")[:20]
                    ls = (p.get("last_studied") or "").strip()
                    if ls:
                        lines.append(f"· {t} ✓")
                    else:
                        lines.append(f"· {t}")
                self.query_one("#study-list", Static).update("\n".join(lines))
            else:
                self.query_one("#study-list", Static).update("none")
        except Exception:
            pass

    def action_toggle_thinking(self) -> None:
        self._show_thinking = not self._show_thinking
        status = "ON" if self._show_thinking else "OFF"
        self.query_one("#think-status", Static).update(f"[think: {status}]")

    def action_do_wakeup(self) -> None:
        import asyncio
        asyncio.create_task(self._do_wakeup())


if __name__ == "__main__":
    app = LaylaApp()
    app.run()
