"""
Discord Bot setup wizard for Layla.

Interactive CLI that guides through:
1. Bot token validation
2. Layla API URL configuration
3. Writing .env / runtime_config.json
4. Optional: invite URL generation

Run: python -m discord_bot.installer
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Add agent to path for runtime_safety access
_agent = Path(__file__).resolve().parent.parent / "agent"
if str(_agent) not in sys.path:
    sys.path.insert(0, str(_agent))

BOT_DIR = Path(__file__).resolve().parent
ENV_FILE = BOT_DIR / ".env"
REQUIRED_PERMISSIONS = 3_267_584  # Send Messages, Embed Links, Connect, Speak, Use Slash Commands
REQUIRED_INTENTS = ["guilds", "guild_messages", "guild_voice_states", "message_content"]


def _print_header() -> None:
    print("\n" + "=" * 60)
    print("    ⚔️  LAYLA DISCORD BOT — SETUP WIZARD  ⚔️")
    print("=" * 60)
    print()


def _print_step(n: int, text: str) -> None:
    print(f"\n  [{n}] {text}")
    print("  " + "-" * 50)


def _validate_token_format(token: str) -> bool:
    """Basic format check for Discord bot token."""
    token = token.strip()
    if not token:
        return False
    parts = token.split(".")
    if len(parts) != 3:
        return False
    if len(token) < 50:
        return False
    return True


async def _validate_token_live(token: str) -> tuple[bool, str]:
    """Validate token by calling Discord API."""
    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            headers = {"Authorization": f"Bot {token}"}
            async with session.get("https://discord.com/api/v10/users/@me", headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return True, data.get("username", "Unknown")
                elif resp.status == 401:
                    return False, "Invalid token (401 Unauthorized)"
                else:
                    return False, f"Discord API returned status {resp.status}"
    except ImportError:
        # No aiohttp — can't validate live, accept format-valid tokens
        return True, "(live validation skipped — aiohttp not installed)"
    except Exception as e:
        return False, f"Connection error: {e}"


def _generate_invite_url(client_id: str) -> str:
    """Generate a Discord bot invite URL with required permissions."""
    return (
        f"https://discord.com/api/oauth2/authorize"
        f"?client_id={client_id}"
        f"&permissions={REQUIRED_PERMISSIONS}"
        f"&scope=bot%20applications.commands"
    )


def _write_env_file(token: str, api_url: str) -> None:
    """Write or update the .env file."""
    lines = []
    if ENV_FILE.exists():
        existing = ENV_FILE.read_text(encoding="utf-8").splitlines()
        for line in existing:
            key = line.split("=")[0].strip() if "=" in line else ""
            if key not in ("DISCORD_BOT_TOKEN", "DISCORD_TOKEN", "LAYLA_BASE_URL"):
                lines.append(line)

    lines.append(f"DISCORD_BOT_TOKEN={token}")
    lines.append(f"LAYLA_BASE_URL={api_url}")

    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  ✅ Written to {ENV_FILE}")


def _update_runtime_config(token: str, api_url: str) -> None:
    """Optionally update Layla's runtime_config.json."""
    try:
        import runtime_safety
        config_path = runtime_safety.CONFIG_FILE
        data = {}
        if config_path.exists():
            try:
                data = json.loads(config_path.read_text(encoding="utf-8"))
            except Exception:
                data = {}

        data["discord_bot_token"] = token
        if api_url != "http://localhost:8000":
            data["layla_api_url"] = api_url
        data["discord_bot_autostart"] = True

        config_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"  ✅ Updated {config_path}")
    except Exception as e:
        print(f"  ⚠️  Could not update runtime_config.json: {e}")


def run_setup() -> bool:
    """Run the interactive setup wizard. Returns True if successful."""
    _print_header()

    # Step 1: Bot Token
    _print_step(1, "Discord Bot Token")
    print("  Go to https://discord.com/developers/applications")
    print("  Create a new application → Bot → Copy token")
    print()
    token = input("  Paste your bot token: ").strip()

    if not _validate_token_format(token):
        print("\n  ❌ Invalid token format. Expected format: XXXX.XXXX.XXXX (3 dot-separated parts)")
        return False

    # Try live validation
    try:
        import asyncio
        loop = asyncio.new_event_loop()
        valid, info = loop.run_until_complete(_validate_token_live(token))
        loop.close()
        if not valid:
            print(f"\n  ❌ Token validation failed: {info}")
            return False
        print(f"\n  ✅ Token valid! Bot username: {info}")
    except Exception:
        print("\n  ⚠️  Could not validate token (offline mode). Proceeding...")

    # Step 2: Layla API URL
    _print_step(2, "Layla API URL")
    print("  Where is Layla's server running?")
    print("  Default: http://localhost:8000")
    print()
    api_url = input("  API URL [http://localhost:8000]: ").strip()
    if not api_url:
        api_url = "http://localhost:8000"

    # Step 3: Write config
    _print_step(3, "Writing configuration")
    _write_env_file(token, api_url)

    update_runtime = input("\n  Also update runtime_config.json? [Y/n]: ").strip().lower()
    if update_runtime != "n":
        _update_runtime_config(token, api_url)

    # Step 4: Invite URL
    _print_step(4, "Invite your bot")
    print("  You need the bot's Client ID (Application → General → Application ID)")
    client_id = input("  Client ID (or press Enter to skip): ").strip()
    if client_id:
        url = _generate_invite_url(client_id)
        print(f"\n  🔗 Invite URL:\n  {url}")
        print("\n  Open this URL to add Layla to your Discord server.")
    else:
        print("  Skipped. You can generate an invite URL from the Developer Portal.")

    # Done
    print("\n" + "=" * 60)
    print("  ✅ SETUP COMPLETE!")
    print()
    print("  Start the bot:")
    print("    python -m discord_bot.run")
    print()
    print("  Or enable auto-start in runtime_config.json:")
    print('    "discord_bot_autostart": true')
    print("=" * 60 + "\n")

    return True


# ── Module entry point ───────────────────────────────────────────────────────

if __name__ == "__main__":
    success = run_setup()
    sys.exit(0 if success else 1)
