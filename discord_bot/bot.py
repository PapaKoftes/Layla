"""
Layla Discord Bot — summon, chat->speak, multi-source music, per-channel config.

Flow:
  /summon  — Join your voice channel, bind to this text channel. Stays until /dismiss.
  Chat in the bound channel (or @mention) -> she replies; if TTS on, she speaks.
  /play <url|query> — YouTube, Spotify, SoundCloud, Bandcamp, search. Works in any channel.
  /config tts on|off, /config music on|off — Per-channel permissions.

Requires: py-cord[voice], aiohttp, FFmpeg.
Optional: yt-dlp (music), spotdl (Spotify), kokoro-onnx (TTS).
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import tempfile
import time
from pathlib import Path

_agent = Path(__file__).resolve().parent.parent / "agent"
if str(_agent) not in sys.path:
    sys.path.insert(0, str(_agent))

logger = logging.getLogger("layla.discord")

# ---------------------------------------------------------------------------
# Optional dependency guards
# ---------------------------------------------------------------------------

try:
    import discord
    from discord import app_commands
    from discord.ext import commands
    _DISCORD_OK = True
except ImportError:
    discord = None  # type: ignore
    app_commands = None  # type: ignore
    commands = None  # type: ignore
    _DISCORD_OK = False

_YTDLP_OK = False
try:
    import yt_dlp  # noqa: F401
    _YTDLP_OK = True
except ImportError:
    pass

_VOICE_OK = False
try:
    import nacl  # noqa: F401
    _VOICE_OK = True
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Imports from our codebase
# ---------------------------------------------------------------------------

from transports.base import call_layla_async, check_transport_inbound, save_learning_async
from .config import (
    get_agent_url,
    get_command_prefix,
    get_max_response_chars,
    get_music_default,
    get_tts_default,
)
from .state import (
    append_queue,
    clear_queue,
    get_guild_state,
    get_queue,
    get_queue_titles,
    get_text_channel_id,
    get_voice_channel_id,
    get_voice_client,
    is_listening,
    is_playing,
    is_summoned,
    music_enabled,
    pop_queue,
    pop_voice_client,
    set_guild_state,
    set_listening,
    set_playing,
    set_voice_client,
    tts_enabled,
)

# ---------------------------------------------------------------------------
# Rate limiting: debounce per-channel (2 s)
# ---------------------------------------------------------------------------

_last_call: dict[int, float] = {}  # channel_id -> timestamp
_RATE_LIMIT_SECS = 2.0


def _rate_limited(channel_id: int) -> bool:
    now = time.monotonic()
    last = _last_call.get(channel_id, 0.0)
    if now - last < _RATE_LIMIT_SECS:
        return True
    _last_call[channel_id] = now
    return False


# ---------------------------------------------------------------------------
# TTS helpers
# ---------------------------------------------------------------------------

def _get_tts_bytes_sync(text: str) -> bytes | None:
    """Synchronous TTS call. Wrap with asyncio.to_thread when calling from async."""
    try:
        from services.tts import speak_to_bytes  # type: ignore[import]
        return speak_to_bytes(text[:500])
    except Exception as e:
        logger.warning("TTS failed: %s", e)
        return None


async def _get_tts_bytes(text: str) -> bytes | None:
    """Async wrapper around the sync TTS call."""
    return await asyncio.to_thread(_get_tts_bytes_sync, text)


def _temp_wav(wav: bytes) -> str:
    f = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    f.write(wav)
    f.flush()
    f.close()  # must close before FFmpeg can open it on Windows
    return f.name


def _cleanup_temp(path: str) -> None:
    try:
        if path and os.path.exists(path):
            os.unlink(path)
    except Exception:
        pass


async def _speak_in_voice(guild_id: int, text: str) -> None:
    """Generate TTS and play in the voice channel (fire and forget)."""
    vc = get_voice_client(guild_id)
    if not vc or not vc.is_connected():
        return
    if not _DISCORD_OK:
        return
    wav = await _get_tts_bytes(text[:500])
    if not wav:
        return
    fname = _temp_wav(wav)
    try:
        source = discord.FFmpegPCMAudio(fname, options="-vn -ac 1 -ar 48000")
        source = discord.PCMVolumeTransformer(source, volume=0.5)
        vc.play(source, after=lambda e: _cleanup_temp(fname))
    except Exception as ex:
        logger.warning("TTS play failed: %s", ex)
        _cleanup_temp(fname)


# ---------------------------------------------------------------------------
# Layla API helpers
# ---------------------------------------------------------------------------

async def _call_layla(message: str, aspect_id: str = "morrigan", persona_focus: str = "") -> str:
    try:
        return await call_layla_async(
            message,
            aspect_id=aspect_id,
            max_response_chars=get_max_response_chars(),
            persona_focus=persona_focus or "",
        )
    except Exception as e:
        err = str(e).lower()
        if "connection refused" in err or "cannot connect" in err or "connect call failed" in err:
            return (
                "Layla server is offline. Start it with: "
                "`python -m uvicorn agent.main:app --host 127.0.0.1 --port 8000`"
            )
        logger.exception("_call_layla failed: %s", e)
        return f"Error reaching Layla: {e}"


async def _save_operator_note(content: str) -> str:
    """Explicit learnings entry (ethics: user-initiated only)."""
    data = await save_learning_async(content.strip(), kind="fact", tags="discord:explicit_note")
    if data.get("ok"):
        return "Saved to Layla learnings."
    return data.get("error", "Could not save note.") or "Could not save note."


def _discord_inbound_ok(user_id: int, text: str | None) -> tuple[bool, str | None]:
    return check_transport_inbound("discord", str(user_id), text)


# ---------------------------------------------------------------------------
# Message splitting helper
# ---------------------------------------------------------------------------

def _split_message(text: str, limit: int | None = None) -> list[str]:
    """Split a long message into chunks of at most `limit` chars."""
    limit = limit or get_max_response_chars()
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    while text:
        chunks.append(text[:limit])
        text = text[limit:]
    return chunks


# ---------------------------------------------------------------------------
# Music player helpers
# ---------------------------------------------------------------------------

def _play_next(guild_id: int) -> None:
    """Pop next track from queue and start playing. Called from after= callback (sync)."""
    item = pop_queue(guild_id)
    if not item:
        set_playing(guild_id, False)
        return
    vc = get_voice_client(guild_id)
    if not vc or not vc.is_connected():
        set_playing(guild_id, False)
        return
    url = item.get("url")
    if not url:
        _play_next(guild_id)
        return
    try:
        source = discord.FFmpegPCMAudio(
            url,
            before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
            options="-vn -ac 2 -ar 48000",
        )
        source = discord.PCMVolumeTransformer(source, volume=0.5)
        vc.play(source, after=lambda e: _play_next(guild_id))
        set_playing(guild_id, True)
    except Exception as ex:
        logger.warning("Play failed: %s", ex)
        _play_next(guild_id)


# ---------------------------------------------------------------------------
# Bot factory
# ---------------------------------------------------------------------------

def _create_bot() -> "commands.Bot | None":  # type: ignore[return]
    if not _DISCORD_OK:
        logger.error("py-cord not installed. Run: pip install 'py-cord[voice]'")
        return None
    if not _VOICE_OK:
        logger.warning(
            "PyNaCl not found — voice features will be disabled. "
            "Run: pip install pynacl  (or pip install 'py-cord[voice]')"
        )

    intents = discord.Intents.default()
    intents.message_content = True
    intents.voice_states = True

    bot = commands.Bot(command_prefix=get_command_prefix(), intents=intents)

    # -----------------------------------------------------------------------
    # Events
    # -----------------------------------------------------------------------

    @bot.event
    async def on_ready():
        logger.info(
            "Layla Discord bot ready as %s (guilds: %d)",
            bot.user,
            len(bot.guilds),
        )
        try:
            synced = await bot.tree.sync()
            logger.info("Synced %d slash commands", len(synced))
        except Exception as e:
            logger.warning("Command sync failed: %s", e)

    @bot.event
    async def on_voice_state_update(member, before, after):
        """Detect if bot was kicked/disconnected from voice."""
        if not bot.user:
            return
        if member.id != bot.user.id:
            return
        if before.channel is not None and after.channel is None:
            # Bot was disconnected
            guild_id = before.channel.guild.id
            vc = pop_voice_client(guild_id)
            set_playing(guild_id, False)
            clear_queue(guild_id)
            logger.info("Bot disconnected from voice in guild %s", guild_id)

    # -----------------------------------------------------------------------
    # /summon
    # -----------------------------------------------------------------------

    @bot.tree.command(name="summon", description="Summon Layla into your voice channel and bind to this text channel")
    async def summon(interaction: discord.Interaction):
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message(
                "You must be in a voice channel to summon me.", ephemeral=True
            )
            return
        vc_ch = interaction.user.voice.channel
        guild_id = interaction.guild_id
        text_ch = interaction.channel_id

        try:
            vc = get_voice_client(guild_id)
            if vc and vc.is_connected():
                await vc.move_to(vc_ch)
            else:
                vc = await vc_ch.connect()
                set_voice_client(guild_id, vc)
        except Exception as e:
            logger.warning("Voice connect failed: %s", e)
            await interaction.response.send_message(
                f"Could not join voice channel: {e}\n"
                "Make sure FFmpeg is in PATH and PyNaCl is installed.",
                ephemeral=True,
            )
            return

        set_guild_state(
            guild_id,
            voice_channel_id=vc_ch.id,
            text_channel_id=text_ch,
            tts_enabled=get_tts_default(),
            music_enabled=get_music_default(),
        )
        await interaction.response.send_message(
            f"Summoned to **{vc_ch.name}**. I'll respond to all messages in this channel. "
            f"TTS is {'on' if get_tts_default() else 'off'} by default — use `/config tts on` to enable."
        )

    # -----------------------------------------------------------------------
    # /dismiss
    # -----------------------------------------------------------------------

    @bot.tree.command(name="dismiss", description="Dismiss Layla from voice and unbind text channel")
    async def dismiss(interaction: discord.Interaction):
        guild_id = interaction.guild_id
        vc = pop_voice_client(guild_id)
        if vc and vc.is_connected():
            await vc.disconnect()
        set_guild_state(guild_id, voice_channel_id=None, text_channel_id=None)
        clear_queue(guild_id)
        set_playing(guild_id, False)
        await interaction.response.send_message("Dismissed. Goodbye.")

    # -----------------------------------------------------------------------
    # /join  /leave (voice-only, no chat binding)
    # -----------------------------------------------------------------------

    @bot.tree.command(name="join", description="Join your voice channel (music-only, no chat binding)")
    async def join(interaction: discord.Interaction):
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message("You must be in a voice channel.", ephemeral=True)
            return
        vc_ch = interaction.user.voice.channel
        guild_id = interaction.guild_id
        try:
            vc = get_voice_client(guild_id)
            if vc and vc.is_connected():
                await vc.move_to(vc_ch)
            else:
                vc = await vc_ch.connect()
                set_voice_client(guild_id, vc)
        except Exception as e:
            await interaction.response.send_message(
                f"Could not join voice: {e}", ephemeral=True
            )
            return
        await interaction.response.send_message(f"Joined **{vc_ch.name}**.")

    @bot.tree.command(name="leave", description="Leave voice channel")
    async def leave(interaction: discord.Interaction):
        guild_id = interaction.guild_id
        vc = pop_voice_client(guild_id)
        if vc and vc.is_connected():
            await vc.disconnect()
        clear_queue(guild_id)
        set_playing(guild_id, False)
        await interaction.response.send_message("Left voice channel.")

    # -----------------------------------------------------------------------
    # /config
    # -----------------------------------------------------------------------

    @bot.tree.command(name="config", description="Per-channel config: 'tts' or 'music', value 'on' or 'off'")
    @app_commands.describe(setting="tts or music", value="on or off")
    async def config_cmd(interaction: discord.Interaction, setting: str, value: str):
        guild_id = interaction.guild_id
        v = value.lower() in ("on", "1", "true", "yes")
        s = setting.lower()
        if s == "tts":
            set_guild_state(guild_id, tts_enabled=v)
            await interaction.response.send_message(f"TTS is now **{'on' if v else 'off'}** in this channel.")
        elif s == "music":
            set_guild_state(guild_id, music_enabled=v)
            await interaction.response.send_message(f"Music is now **{'on' if v else 'off'}** in this channel.")
        else:
            await interaction.response.send_message(
                "Usage: `/config tts on|off` or `/config music on|off`", ephemeral=True
            )

    # -----------------------------------------------------------------------
    # /status
    # -----------------------------------------------------------------------

    @bot.tree.command(name="status", description="Show Layla server status")
    async def status(interaction: discord.Interaction):
        await interaction.response.defer()
        import aiohttp  # type: ignore[import]
        base = get_agent_url()
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{base}/health", timeout=aiohttp.ClientTimeout(total=5)
                ) as resp:
                    data = await resp.json()
                    status_str = data.get("status", "unknown")
                    await interaction.followup.send(
                        f"Layla server: **{status_str}** (HTTP {resp.status}) at `{base}`"
                    )
        except Exception as e:
            await interaction.followup.send(
                f"Layla server at `{base}` is **offline** or unreachable: `{e}`\n"
                "Start it with: `python -m uvicorn agent.main:app`"
            )

    # -----------------------------------------------------------------------
    # /ping
    # -----------------------------------------------------------------------

    @bot.tree.command(name="ping", description="Check bot latency")
    async def ping(interaction: discord.Interaction):
        latency_ms = round(bot.latency * 1000)
        await interaction.response.send_message(f"Pong! Latency: **{latency_ms}ms**")

    # -----------------------------------------------------------------------
    # /ask
    # -----------------------------------------------------------------------

    @bot.tree.command(name="ask", description="Ask Layla a question (text reply)")
    @app_commands.describe(question="What to ask Layla")
    async def ask(interaction: discord.Interaction, question: str):
        ok, deny = _discord_inbound_ok(interaction.user.id, question)
        if not ok:
            await interaction.response.send_message(deny or "Unauthorized.", ephemeral=True)
            return
        await interaction.response.defer()
        reply = await _call_layla(question)
        chunks = _split_message(reply)
        await interaction.followup.send(chunks[0])
        for chunk in chunks[1:]:
            await interaction.followup.send(chunk)

    # -----------------------------------------------------------------------
    # /note
    # -----------------------------------------------------------------------

    @bot.tree.command(name="note", description="Save a note to Layla learnings (operator-initiated only)")
    @app_commands.describe(text="Text to remember")
    async def note(interaction: discord.Interaction, text: str):
        ok, deny = _discord_inbound_ok(interaction.user.id, text)
        if not ok:
            await interaction.response.send_message(deny or "Unauthorized.", ephemeral=True)
            return
        await interaction.response.defer()
        msg = await _save_operator_note(text)
        await interaction.followup.send(msg[:500])

    # -----------------------------------------------------------------------
    # /chat_speak
    # -----------------------------------------------------------------------

    @bot.tree.command(name="chat_speak", description="Ask Layla and she speaks the reply in voice")
    @app_commands.describe(message="What to ask Layla")
    async def chat_speak(interaction: discord.Interaction, message: str):
        ok, deny = _discord_inbound_ok(interaction.user.id, message)
        if not ok:
            await interaction.response.send_message(deny or "Unauthorized.", ephemeral=True)
            return
        vc = get_voice_client(interaction.guild_id)
        if not vc or not vc.is_connected():
            await interaction.response.send_message("Summon me first with /summon.", ephemeral=True)
            return
        await interaction.response.defer()
        reply = await _call_layla(message)
        if not reply:
            await interaction.followup.send("Layla didn't respond.")
            return
        chunks = _split_message(reply)
        await interaction.followup.send(chunks[0])
        for chunk in chunks[1:]:
            await interaction.followup.send(chunk)
        asyncio.ensure_future(_speak_in_voice(interaction.guild_id, reply[:500]))

    # -----------------------------------------------------------------------
    # /tts  /say
    # -----------------------------------------------------------------------

    @bot.tree.command(name="tts", description="Speak text in voice channel (TTS)")
    @app_commands.describe(message="Text to speak")
    async def tts_cmd(interaction: discord.Interaction, message: str):
        vc = get_voice_client(interaction.guild_id)
        if not vc or not vc.is_connected():
            await interaction.response.send_message("Summon me first with /summon.", ephemeral=True)
            return
        await interaction.response.defer()
        wav = await _get_tts_bytes(message)
        if not wav:
            await interaction.followup.send(
                "TTS unavailable. Install: `pip install kokoro-onnx soundfile`", ephemeral=True
            )
            return
        fname = _temp_wav(wav)
        try:
            source = discord.FFmpegPCMAudio(fname, options="-vn -ac 1 -ar 48000")
            source = discord.PCMVolumeTransformer(source, volume=0.5)
            vc.play(source, after=lambda e: _cleanup_temp(fname))
        except Exception as ex:
            logger.warning("TTS play failed: %s", ex)
            _cleanup_temp(fname)
            await interaction.followup.send(f"TTS play failed: {ex}", ephemeral=True)
            return
        await interaction.followup.send("Speaking...")

    @bot.tree.command(name="say", description="Alias for /tts — speak text in voice")
    @app_commands.describe(message="Text to speak")
    async def say(interaction: discord.Interaction, message: str):
        await tts_cmd.callback(interaction, message)

    # -----------------------------------------------------------------------
    # Voice listen / stop_listen
    # -----------------------------------------------------------------------

    def _transcribe_wav(path: str) -> str:
        try:
            from services.stt import transcribe_file  # type: ignore[import]
            return (transcribe_file(path) or "").strip()
        except Exception as e:
            logger.warning("STT failed: %s", e)
            return ""

    async def _on_voice_recording_done(sink, channel, *args):
        try:
            set_listening(channel.guild.id, None)
            all_text: list[str] = []
            for user_id, audio in getattr(sink, "audio_data", {}).items():
                path = getattr(audio, "file", None)
                if path and os.path.exists(path):
                    t = await asyncio.to_thread(_transcribe_wav, path)
                    if t:
                        all_text.append(t)
                    _cleanup_temp(path)
            text = " ".join(all_text).strip()
            if not text:
                await channel.send("Could not transcribe. Install faster-whisper.")
                return
            uids = [str(u) for u in getattr(sink, "audio_data", {}).keys()]
            for uid in uids:
                ok, deny = check_transport_inbound("discord", uid, None)
                if not ok:
                    await channel.send((deny or "Unauthorized.")[:2000])
                    return
            await channel.send(f"You said: {text[:200]}")
            reply = await _call_layla(text)
            for chunk in _split_message(reply):
                await channel.send(chunk)
            if tts_enabled(channel.guild.id, channel.id):
                asyncio.ensure_future(_speak_in_voice(channel.guild.id, reply[:500]))
        except Exception as e:
            logger.exception("Voice recording callback failed: %s", e)

    @bot.tree.command(name="listen", description="Start listening to voice — transcribe, reply, speak when done")
    async def listen(interaction: discord.Interaction):
        vc = get_voice_client(interaction.guild_id)
        if not vc or not vc.is_connected():
            await interaction.response.send_message("Summon me first with /summon.", ephemeral=True)
            return
        if is_listening(interaction.guild_id):
            await interaction.response.send_message(
                "Already listening. Use /stop_listen when done.", ephemeral=True
            )
            return
        try:
            sink = discord.sinks.WaveSink()
            vc.start_recording(sink, _on_voice_recording_done, interaction.channel)
            set_listening(interaction.guild_id, interaction.channel.id)
            await interaction.response.send_message("Listening. Speak, then use /stop_listen.")
        except AttributeError:
            await interaction.response.send_message(
                "Voice receive not supported. Update py-cord.", ephemeral=True
            )
        except Exception as e:
            logger.exception("Listen failed: %s", e)
            await interaction.response.send_message(f"Listen failed: {e}", ephemeral=True)

    @bot.tree.command(name="stop_listen", description="Stop listening and process what you said")
    async def stop_listen(interaction: discord.Interaction):
        vc = get_voice_client(interaction.guild_id)
        if not vc or not vc.is_connected():
            await interaction.response.send_message("Not in voice.", ephemeral=True)
            return
        if not is_listening(interaction.guild_id):
            await interaction.response.send_message("Not currently listening.", ephemeral=True)
            return
        try:
            vc.stop_recording()
            await interaction.response.send_message("Processing your voice input...")
        except Exception as e:
            logger.exception("stop_listen failed: %s", e)
            await interaction.response.send_message(f"Failed: {e}", ephemeral=True)

    # -----------------------------------------------------------------------
    # Music commands
    # -----------------------------------------------------------------------

    @bot.tree.command(name="play", description="Play music from YouTube, Spotify, SoundCloud, Bandcamp, or search")
    @app_commands.describe(query="URL or search query")
    async def play(interaction: discord.Interaction, query: str):
        guild_id = interaction.guild_id
        vc = get_voice_client(guild_id)
        if not vc or not vc.is_connected():
            await interaction.response.send_message(
                "I'm not in a voice channel. Use /summon or /join first.", ephemeral=True
            )
            return
        if not music_enabled(guild_id):
            await interaction.response.send_message(
                "Music is disabled in this channel. Use `/config music on`.", ephemeral=True
            )
            return
        if not _YTDLP_OK:
            await interaction.response.send_message(
                "yt-dlp is not installed. Run: `pip install yt-dlp`", ephemeral=True
            )
            return
        await interaction.response.defer()
        try:
            from .music_resolver import resolve_async
            result = await resolve_async(query)
        except Exception as e:
            await interaction.followup.send(f"Music resolver error: {e}")
            return
        if not result:
            await interaction.followup.send(
                "Could not resolve that. Try a YouTube/Spotify URL or different search query."
            )
            return
        append_queue(guild_id, result)
        q = get_queue(guild_id)
        position = len(q)
        if not is_playing(guild_id):
            _play_next(guild_id)
            embed = discord.Embed(
                title="Now Playing",
                description=f"**{result.get('title', 'Unknown')}**",
                color=discord.Color.green(),
            )
            if result.get("url"):
                embed.add_field(name="Requested by", value=str(interaction.user), inline=True)
            await interaction.followup.send(embed=embed)
        else:
            await interaction.followup.send(
                f"Added **{result.get('title', '?')}** to the queue (position {position})."
            )

    @bot.tree.command(name="skip", description="Skip the current track")
    async def skip(interaction: discord.Interaction):
        guild_id = interaction.guild_id
        vc = get_voice_client(guild_id)
        if not vc or not vc.is_connected():
            await interaction.response.send_message("Not in a voice channel.", ephemeral=True)
            return
        if not vc.is_playing() and not vc.is_paused():
            await interaction.response.send_message("Nothing is playing.", ephemeral=True)
            return
        vc.stop()  # triggers after= callback -> _play_next
        await interaction.response.send_message("Skipped.")

    @bot.tree.command(name="queue", description="Show the current music queue (up to 10 tracks)")
    async def queue_cmd(interaction: discord.Interaction):
        guild_id = interaction.guild_id
        titles = get_queue_titles(guild_id)
        if not titles:
            await interaction.response.send_message("The queue is empty.")
            return
        lines = [f"{i + 1}. {t}" for i, t in enumerate(titles[:10])]
        total = len(titles)
        footer = f"\n... and {total - 10} more" if total > 10 else ""
        await interaction.response.send_message("**Queue:**\n" + "\n".join(lines) + footer)

    @bot.tree.command(name="stop", description="Stop music and clear the queue")
    async def stop(interaction: discord.Interaction):
        guild_id = interaction.guild_id
        vc = get_voice_client(guild_id)
        if not vc:
            await interaction.response.send_message("Not in a voice channel.", ephemeral=True)
            return
        clear_queue(guild_id)
        set_playing(guild_id, False)
        if vc.is_playing() or vc.is_paused():
            vc.stop()
        await interaction.response.send_message("Stopped and queue cleared.")

    @bot.tree.command(name="pause", description="Pause playback")
    async def pause(interaction: discord.Interaction):
        vc = get_voice_client(interaction.guild_id)
        if vc and vc.is_playing():
            vc.pause()
            await interaction.response.send_message("Paused.")
        else:
            await interaction.response.send_message("Nothing is playing.", ephemeral=True)

    @bot.tree.command(name="resume", description="Resume playback")
    async def resume(interaction: discord.Interaction):
        vc = get_voice_client(interaction.guild_id)
        if vc and vc.is_paused():
            vc.resume()
            await interaction.response.send_message("Resumed.")
        else:
            await interaction.response.send_message("Nothing is paused.", ephemeral=True)

    # -----------------------------------------------------------------------
    # on_message: respond to all messages in bound channel, or @mentions
    # -----------------------------------------------------------------------

    @bot.event
    async def on_message(message: discord.Message):
        if message.author.bot:
            return
        guild_id = message.guild.id if message.guild else None
        if not guild_id:
            return

        text_ch = get_text_channel_id(guild_id)
        summoned = is_summoned(guild_id)

        # Determine if we should respond
        bot_mentioned = bot.user and bot.user.mentioned_in(message)
        in_bound_channel = text_ch == message.channel.id

        should_respond = bot_mentioned or (summoned and in_bound_channel)
        if not should_respond:
            await bot.process_commands(message)
            return

        # Strip mention prefix if present
        content = message.content
        if bot.user:
            content = content.replace(f"<@{bot.user.id}>", "").replace(f"<@!{bot.user.id}>", "").strip()

        if not content:
            await message.channel.send("Yes? Say something after the mention.")
            await bot.process_commands(message)
            return

        # Rate limiting
        if _rate_limited(message.channel.id):
            await bot.process_commands(message)
            return

        # Inbound security check
        ok, deny = _discord_inbound_ok(message.author.id, content)
        if not ok:
            if deny:
                await message.channel.send(deny[:2000])
            await bot.process_commands(message)
            return

        # Call Layla with typing indicator
        async with message.channel.typing():
            reply = await _call_layla(content)

        if not reply:
            await message.channel.send("Layla didn't respond.")
            await bot.process_commands(message)
            return

        # Split and send long messages
        for chunk in _split_message(reply):
            await message.channel.send(chunk)

        # TTS if enabled and in voice
        if tts_enabled(guild_id, message.channel.id):
            vc = get_voice_client(guild_id)
            if vc and vc.is_connected():
                asyncio.ensure_future(_speak_in_voice(guild_id, reply[:500]))

        await bot.process_commands(message)

    return bot
