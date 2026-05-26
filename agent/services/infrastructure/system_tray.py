# -*- coding: utf-8 -*-
"""
system_tray.py — System tray icon for Layla.

Shows current resource mode and offers quick controls via right-click menu.
Requires pystray (optional dependency — degrades gracefully if missing).

Config key:
    system_tray_enabled    bool  (default True on Windows, False elsewhere)
"""
from __future__ import annotations

import io
import logging
import platform
import threading
import webbrowser
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from services.resource_governor import ResourceGovernor

logger = logging.getLogger("layla.tray")

_IS_WINDOWS = platform.system() == "Windows"
_tray_thread: threading.Thread | None = None
_tray_icon = None


def _create_icon_image(mode: str = "whisper"):
    """
    Create a simple coloured icon for the tray.

    Colours:
      whisper  → dim blue  (minimal activity)
      breathe  → amber     (moderate)
      sprint   → green     (full power)
    """
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        # Minimal fallback: 16x16 solid colour
        return None

    colours = {
        "whisper": "#4A6FA5",
        "breathe": "#D4A843",
        "sprint": "#4CAF50",
    }
    colour = colours.get(mode, "#4A6FA5")

    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Draw a circle with the mode colour
    draw.ellipse([4, 4, 60, 60], fill=colour, outline="#FFFFFF", width=2)
    # Draw "L" in the centre
    try:
        draw.text((22, 14), "L", fill="#FFFFFF")
    except Exception:
        pass
    return img


def _make_menu(governor: ResourceGovernor | None = None):
    """Build the right-click context menu."""
    try:
        import pystray
    except ImportError:
        return None

    mode_str = governor.mode.value if governor else "unknown"
    state = governor.to_dict() if governor else {}
    cpu_pct = state.get("cpu_percent", 0)
    workers = state.get("max_workers", 0)

    def open_ui(_icon, _item):
        webbrowser.open("http://localhost:8000/ui")

    def set_whisper(_icon, _item):
        if governor:
            from services.resource_governor import ResourceMode
            governor._mode = ResourceMode.WHISPER
            _update_tray_state(governor)

    def set_breathe(_icon, _item):
        if governor:
            from services.resource_governor import ResourceMode
            governor._mode = ResourceMode.BREATHE
            _update_tray_state(governor)

    def set_sprint(_icon, _item):
        if governor:
            from services.resource_governor import ResourceMode
            governor._mode = ResourceMode.SPRINT
            _update_tray_state(governor)

    def quit_layla(_icon, _item):
        _icon.stop()

    return pystray.Menu(
        pystray.MenuItem(
            f"Layla - {mode_str.upper()} ({cpu_pct:.0f}% CPU, {workers} workers)",
            open_ui,
            default=True,
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Open Layla UI", open_ui),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Mode", pystray.Menu(
            pystray.MenuItem("Whisper (minimal)", set_whisper),
            pystray.MenuItem("Breathe (moderate)", set_breathe),
            pystray.MenuItem("Sprint (full power)", set_sprint),
        )),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Stop Layla", quit_layla),
    )


def _update_tray_state(governor: ResourceGovernor | None = None):
    """Update the tray icon and tooltip to reflect current mode."""
    global _tray_icon
    if _tray_icon is None:
        return
    try:
        mode_str = governor.mode.value if governor else "unknown"
        state = governor.to_dict() if governor else {}
        cpu_pct = state.get("cpu_percent", 0)

        _tray_icon.title = f"Layla - {mode_str.upper()} ({cpu_pct:.0f}% CPU)"
        new_icon = _create_icon_image(mode_str)
        if new_icon:
            _tray_icon.icon = new_icon
        _tray_icon.menu = _make_menu(governor)
    except Exception as exc:
        logger.debug("tray: update failed: %s", exc)


def start_tray(governor: ResourceGovernor | None = None) -> bool:
    """
    Start the system tray icon in a background thread.

    Returns True if started, False if pystray is unavailable.
    """
    global _tray_icon, _tray_thread

    if not _IS_WINDOWS:
        logger.debug("tray: not Windows, skipping")
        return False

    try:
        import pystray
    except ImportError:
        logger.info("tray: pystray not installed, skipping system tray")
        return False

    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        logger.info("tray: Pillow not installed, skipping system tray icon")
        return False

    mode_str = governor.mode.value if governor else "whisper"
    icon_img = _create_icon_image(mode_str)
    if icon_img is None:
        logger.warning("tray: could not create icon image")
        return False

    menu = _make_menu(governor)
    _tray_icon = pystray.Icon(
        "layla",
        icon_img,
        title=f"Layla - {mode_str.upper()}",
        menu=menu,
    )

    # Register mode change callback to update tray
    if governor:
        def _on_mode_change(old_mode, new_mode):
            _update_tray_state(governor)
        governor.on_mode_change(_on_mode_change)

    def _run_tray():
        try:
            _tray_icon.run()
        except Exception as exc:
            logger.warning("tray: run failed: %s", exc)

    _tray_thread = threading.Thread(target=_run_tray, name="system-tray", daemon=True)
    _tray_thread.start()
    logger.info("tray: system tray started")
    return True


def stop_tray():
    """Stop the system tray icon."""
    global _tray_icon
    if _tray_icon:
        try:
            _tray_icon.stop()
        except Exception:
            pass
        _tray_icon = None
