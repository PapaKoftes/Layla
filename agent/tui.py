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
    /export            Dump system state to layla_export.json
"""
import json
import sys
from datetime import datetime
from pathlib import Path

import httpx
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import (
    Footer, Header, Input, Label, ListView, ListItem, Log, Static
)
from textual.containers import Horizontal, Vertical, ScrollableContainer
from textual import events

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
                    yield Input(placeholder="Speak to Layla…  (/aspect /think /study /approve /wakeup /export)", id="msg-input")
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
        log.write_line(f"[bold cyan]USER:[/] {text}")
        log.write_line("─── ✦ ───")

        try:
            resp = httpx.post(
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

        elif cmd == "/run":
            self._allow_run = not self._allow_run
            log.write_line(f"[yellow]Allow Run: {'ON' if self._allow_run else 'OFF'}[/]")

        else:
            log.write_line(f"[red]Unknown command: {cmd}[/]")

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
