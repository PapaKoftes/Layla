"""
Layla Discord Bot — summon, chat→speak, multi-source music, per-channel config.

Flow:
  /summon — Join your voice channel, bind to this text channel. Layla stays until /dismiss.
  Chat in the bound channel (or @mention her) → she replies; if TTS enabled, she speaks.
  /play <url|query> — YouTube, Spotify, SoundCloud, Bandcamp, search. Works in any channel.
  /config tts on|off, /config music on|off — Per-channel permissions.

Requires: py-cord[voice], yt-dlp, FFmpeg. Optional: spotdl + Spotify creds for Spotify URLs.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

_agent = Path(__file__).resolve().parent.parent / "agent"
if str(_agent) not in sys.path:
    sys.path.insert(0, str(_agent))

logger = logging.getLogger("layla.discord")

try:
    import discord
    from discord import app_commands
    from discord.ext import commands
except ImportError:
    discord = None  # type: ignore

from transports.base import call_layla_async, check_transport_inbound, save_learning_async
from .state import (
    append_queue,
    clear_queue,
    get_guild_state,
    get_queue,
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


def _get_tts_bytes(text: str) -> bytes | None:
    try:
        from services.tts import speak_to_bytes
        return speak_to_bytes(text[:500])
    except Exception as e:
        logger.warning("TTS failed: %s", e)
        return None


async def _call_layla(message: str, aspect_id: str = "morrigan", persona_focus: str = "") -> str:
    return await call_layla_async(
        message,
        aspect_id=aspect_id,
        max_response_chars=2000,
        persona_focus=persona_focus or "",
    )


async def _save_operator_note(content: str) -> str:
    """Explicit learnings entry (ethics: user-initiated only)."""
    data = await save_learning_async(content.strip(), kind="fact", tags="discord:explicit_note")
    if data.get("ok"):
        return "✓ Saved to Layla learnings."
    return data.get("error", "Could not save note.") or "Could not save note."


def _discord_inbound_ok(user_id: int, text: str | None) -> tuple[bool, str | None]:
    return check_transport_inbound("discord", str(user_id), text)


def _create_bot() -> commands.Bot | None:
    if discord is None:
        logger.error("py-cord not installed. pip install 'py-cord[voice]'")
        return None

    intents = discord.Intents.default()
    intents.message_content = True
    intents.voice_states = True

    bot = commands.Bot(command_prefix="!", intents=intents)

    @bot.event
    async def on_ready():
        logger.info("Layla Discord bot ready as %s", bot.user)
        try:
            synced = await bot.tree.sync()
            logger.info("Synced %d commands", len(synced))
        except Exception as e:
            logger.warning("Command sync failed: %s", e)

    # --- Summon / Dismiss ---

    @bot.tree.command(name="summon", description="Summon Layla into your voice channel and bind to this text channel")
    async def summon(interaction: discord.Interaction):
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message("You must be in a voice channel.", ephemeral=True)
            return
        vc_ch = interaction.user.voice.channel
        guild_id = interaction.guild_id
        text_ch = interaction.channel_id

        # Join or move
        vc = get_voice_client(guild_id)
        if vc and vc.is_connected():
            await vc.move_to(vc_ch)
        else:
            vc = await vc_ch.connect()
            set_voice_client(guild_id, vc)

        set_guild_state(
            guild_id,
            voice_channel_id=vc_ch.id,
            text_channel_id=text_ch,
            tts_enabled=True,
            music_enabled=True,
        )
        await interaction.response.send_message(
            f"Summoned to {vc_ch.name}. Chat here or @mention me — I'll reply and speak if TTS is on."
        )

    @bot.tree.command(name="join", description="Join your voice channel (music-only, no chat binding)")
    async def join(interaction: discord.Interaction):
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message("You must be in a voice channel.", ephemeral=True)
            return
        vc_ch = interaction.user.voice.channel
        guild_id = interaction.guild_id
        vc = get_voice_client(guild_id)
        if vc and vc.is_connected():
            await vc.move_to(vc_ch)
        else:
            vc = await vc_ch.connect()
            set_voice_client(guild_id, vc)
        await interaction.response.send_message(f"Joined {vc_ch.name}")

    @bot.tree.command(name="leave", description="Leave voice channel")
    async def leave(interaction: discord.Interaction):
        guild_id = interaction.guild_id
        vc = pop_voice_client(guild_id)
        if vc and vc.is_connected():
            await vc.disconnect()
        clear_queue(guild_id)
        set_playing(guild_id, False)
        await interaction.response.send_message("Left voice channel.")

    @bot.tree.command(name="dismiss", description="Dismiss Layla from voice and unbind")
    async def dismiss(interaction: discord.Interaction):
        guild_id = interaction.guild_id
        vc = pop_voice_client(guild_id)
        if vc and vc.is_connected():
            await vc.disconnect()
        set_guild_state(guild_id, voice_channel_id=None, text_channel_id=None)
        clear_queue(guild_id)
        set_playing(guild_id, False)
        await interaction.response.send_message("Dismissed.")

    # --- Config ---

    @bot.tree.command(name="config", description="Per-channel config: tts or music on/off")
    @app_commands.describe(setting="tts or music", value="on or off")
    async def config_cmd(interaction: discord.Interaction, setting: str, value: str):
        if not is_summoned(interaction.guild_id):
            await interaction.response.send_message("Summon me first with /summon.", ephemeral=True)
            return
        v = value.lower() in ("on", "1", "true", "yes")
        if setting.lower() == "tts":
            set_guild_state(interaction.guild_id, tts_enabled=v)
            await interaction.response.send_message(f"TTS {'on' if v else 'off'} in this channel.")
        elif setting.lower() == "music":
            set_guild_state(interaction.guild_id, music_enabled=v)
            await interaction.response.send_message(f"Music {'on' if v else 'off'} in this channel.")
        else:
            await interaction.response.send_message("Use: /config tts on|off or /config music on|off", ephemeral=True)

    # --- Voice-in (STT from voice channel) ---

    def _transcribe_wav(path: str) -> str:
        try:
            from services.stt import transcribe_file
            return (transcribe_file(path) or "").strip()
        except Exception as e:
            logger.warning("STT failed: %s", e)
            return ""

    async def _on_voice_recording_done(sink, channel, *args):
        try:
            set_listening(channel.guild.id, None)
            all_text = []
            for user_id, audio in getattr(sink, "audio_data", {}).items():
                path = getattr(audio, "file", None)
                if path and os.path.exists(path):
                    t = _transcribe_wav(path)
                    if t:
                        all_text.append(t)
                    try:
                        os.unlink(path)
                    except Exception:
                        pass
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
            await channel.send(reply[:2000])
            if tts_enabled(channel.guild.id, channel.id):
                vc = get_voice_client(channel.guild.id)
                if vc and vc.is_connected():
                    wav = _get_tts_bytes(reply[:500])
                    if wav:
                        fname = _temp_wav(wav)
                        try:
                            source = discord.FFmpegPCMAudio(fname, options="-vn -ac 1 -ar 48000")
                            vc.play(source, after=lambda e: _cleanup_temp(fname))
                        except Exception as ex:
                            logger.warning("TTS play failed: %s", ex)
                            _cleanup_temp(fname)
        except Exception as e:
            logger.exception("Voice recording callback failed: %s", e)

    @bot.tree.command(name="listen", description="Start listening to voice — transcribe, reply, speak when done")
    async def listen(interaction: discord.Interaction):
        vc = get_voice_client(interaction.guild_id)
        if not vc or not vc.is_connected():
            await interaction.response.send_message("Summon me first with /summon.", ephemeral=True)
            return
        if is_listening(interaction.guild_id):
            await interaction.response.send_message("Already listening. Use /stop_listen when done.", ephemeral=True)
            return
        try:
            sink = discord.sinks.WaveSink()
            vc.start_recording(sink, _on_voice_recording_done, interaction.channel)
            set_listening(interaction.guild_id, interaction.channel.id)
            await interaction.response.send_message("Listening. Speak, then use /stop_listen when done.")
        except AttributeError:
            await interaction.response.send_message("Voice receive not supported. Update py-cord.", ephemeral=True)
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
            await interaction.response.send_message("Not listening.", ephemeral=True)
            return
        try:
            vc.stop_recording()
            await interaction.response.send_message("Processing...")
        except Exception as e:
            logger.exception("Stop listen failed: %s", e)
            await interaction.response.send_message(f"Failed: {e}", ephemeral=True)

    # --- Chat commands ---

    @bot.tree.command(name="ask", description="Chat with Layla (text reply)")
    @app_commands.describe(message="What to ask Layla")
    async def ask(interaction: discord.Interaction, message: str):
        ok, deny = _discord_inbound_ok(interaction.user.id, message)
        if not ok:
            await interaction.response.send_message(deny or "Unauthorized.", ephemeral=True)
            return
        await interaction.response.defer()
        reply = await _call_layla(message)
        await interaction.followup.send(reply[:2000])

    @bot.tree.command(name="note", description="Save an explicit note to Layla learnings (you choose what is stored)")
    @app_commands.describe(content="Text to remember")
    async def note(interaction: discord.Interaction, content: str):
        ok, deny = _discord_inbound_ok(interaction.user.id, content)
        if not ok:
            await interaction.response.send_message(deny or "Unauthorized.", ephemeral=True)
            return
        await interaction.response.defer()
        msg = await _save_operator_note(content)
        await interaction.followup.send(msg[:500])

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
        await interaction.followup.send(reply[:500])
        wav = _get_tts_bytes(reply[:500])
        if wav:
            fname = _temp_wav(wav)
            try:
                source = discord.FFmpegPCMAudio(fname, options="-vn -ac 1 -ar 48000")
                vc.play(source, after=lambda e: _cleanup_temp(fname))
            except Exception as ex:
                logger.warning("TTS play failed: %s", ex)
                _cleanup_temp(fname)

    def _temp_wav(wav: bytes) -> str:
        import tempfile
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

    # --- TTS ---

    @bot.tree.command(name="tts", description="Speak message in voice (TTS)")
    @app_commands.describe(message="Text to speak")
    async def tts(interaction: discord.Interaction, message: str):
        vc = get_voice_client(interaction.guild_id)
        if not vc or not vc.is_connected():
            await interaction.response.send_message("Summon me first with /summon.", ephemeral=True)
            return
        await interaction.response.defer()
        wav = _get_tts_bytes(message)
        if not wav:
            await interaction.followup.send("TTS failed. Install kokoro-onnx.", ephemeral=True)
            return
        fname = _temp_wav(wav)
        try:
            source = discord.FFmpegPCMAudio(fname, options="-vn -ac 1 -ar 48000")
            vc.play(source, after=lambda e: _cleanup_temp(fname))
        except Exception as ex:
            logger.warning("TTS play failed: %s", ex)
            _cleanup_temp(fname)
        await interaction.followup.send("Speaking...")

    @bot.tree.command(name="say", description="Alias for /tts")
    @app_commands.describe(message="Text to speak")
    async def say(interaction: discord.Interaction, message: str):
        await tts.callback(interaction, message)

    # --- Music (multi-source: YT, Spotify, SoundCloud, Bandcamp, search) ---

    def _play_next(guild_id: int) -> None:
        item = pop_queue(guild_id)
        if not item:
            set_playing(guild_id, False)
            return
        vc = get_voice_client(guild_id)
        if not vc or not vc.is_connected():
            return
        url = item.get("url")
        if not url:
            _play_next(guild_id)
            return
        try:
            source = discord.FFmpegPCMAudio(url, options="-vn -ac 1 -ar 48000")
            vc.play(source, after=lambda e: _play_next(guild_id))
            set_playing(guild_id, True)
        except Exception as ex:
            logger.warning("Play failed: %s", ex)
            _play_next(guild_id)

    @bot.tree.command(name="play", description="Play from YouTube, Spotify, SoundCloud, Bandcamp, or search")
    @app_commands.describe(query="URL or search query")
    async def play(interaction: discord.Interaction, query: str):
        vc = get_voice_client(interaction.guild_id)
        if not vc or not vc.is_connected():
            await interaction.response.send_message("Summon me first with /summon.", ephemeral=True)
            return
        if not music_enabled(interaction.guild_id):
            await interaction.response.send_message("Music is disabled in this channel. Use /config music on.", ephemeral=True)
            return
        await interaction.response.defer()
        from .music_resolver import resolve
        result = resolve(query)
        if not result:
            await interaction.followup.send("Could not resolve that. Try a YouTube/Spotify URL or search query.")
            return
        append_queue(interaction.guild_id, result)
        q = get_queue(interaction.guild_id)
        if not is_playing(interaction.guild_id):
            _play_next(interaction.guild_id)
        await interaction.followup.send(f"Added **{result.get('title', '?')}** to queue. ({len(q)} in queue)")

    @bot.tree.command(name="pause", description="Pause playback")
    async def pause(interaction: discord.Interaction):
        vc = get_voice_client(interaction.guild_id)
        if vc and vc.is_playing():
            vc.pause()
            await interaction.response.send_message("Paused.")
        else:
            await interaction.response.send_message("Nothing playing.", ephemeral=True)

    @bot.tree.command(name="resume", description="Resume playback")
    async def resume(interaction: discord.Interaction):
        vc = get_voice_client(interaction.guild_id)
        if vc and vc.is_paused():
            vc.resume()
            await interaction.response.send_message("Resumed.")
        else:
            await interaction.response.send_message("Nothing paused.", ephemeral=True)

    @bot.tree.command(name="stop", description="Stop music and disconnect")
    async def stop(interaction: discord.Interaction):
        vc = get_voice_client(interaction.guild_id)
        if vc:
            clear_queue(interaction.guild_id)
            set_playing(interaction.guild_id, False)
            vc.stop()
            await vc.disconnect()
            pop_voice_client(interaction.guild_id)
            await interaction.response.send_message("Stopped.")
        else:
            await interaction.response.send_message("Not in voice.", ephemeral=True)

    @bot.tree.command(name="skip", description="Skip current track")
    async def skip(interaction: discord.Interaction):
        vc = get_voice_client(interaction.guild_id)
        if vc:
            vc.stop()
            _play_next(interaction.guild_id)
            await interaction.response.send_message("Skipped.")
        else:
            await interaction.response.send_message("Not in voice.", ephemeral=True)

    @bot.tree.command(name="queue", description="Show queue")
    async def queue_cmd(interaction: discord.Interaction):
        from .state import get_queue_titles
        titles = get_queue_titles(interaction.guild_id)
        if not titles:
            await interaction.response.send_message("Queue is empty.")
        else:
            lines = [f"{i+1}. {t}" for i, t in enumerate(titles[:10])]
            await interaction.response.send_message("Queue:\n" + "\n".join(lines))

    # --- on_message: chat in bound channel → Layla replies, speaks if TTS on ---

    @bot.event
    async def on_message(message: discord.Message):
        if message.author.bot:
            return
        guild_id = message.guild.id if message.guild else None
        if not guild_id:
            return
        text_ch = get_text_channel_id(guild_id)
        if text_ch != message.channel.id:
            return
        # Only react when @mentioned
        if bot.user and bot.user.mentioned_in(message):
            content = message.content.replace(f"<@{bot.user.id}>", "").strip()
            if not content:
                await message.channel.send("Say something after the mention.")
                return
            ok, deny = _discord_inbound_ok(message.author.id, content)
            if not ok:
                if deny:
                    await message.channel.send(deny[:2000])
                return
            async with message.channel.typing():
                reply = await _call_layla(content)
            if not reply:
                await message.channel.send("Layla didn't respond.")
                return
            await message.channel.send(reply[:2000])
            if tts_enabled(guild_id, message.channel.id):
                vc = get_voice_client(guild_id)
                if vc and vc.is_connected():
                    wav = _get_tts_bytes(reply[:500])
                    if wav:
                        fname = _temp_wav(wav)
                        try:
                            source = discord.FFmpegPCMAudio(fname, options="-vn -ac 1 -ar 48000")
                            vc.play(source, after=lambda e: _cleanup_temp(fname))
                        except Exception as ex:
                            logger.warning("TTS play failed: %s", ex)
                            _cleanup_temp(fname)
        await bot.process_commands(message)

    return bot
