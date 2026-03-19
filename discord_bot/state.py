"""
Per-guild state: summon binding, channel config (TTS, music), queue.
Persisted to JSON so config survives restarts.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger("layla.discord")

_STATE_PATH = Path(__file__).resolve().parent / "discord_bot_state.json"
_DEFAULT = {"tts_enabled": True, "music_enabled": True}


def _load() -> dict:
    try:
        if _STATE_PATH.exists():
            return json.loads(_STATE_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("Could not load Discord state: %s", e)
    return {}


def _save(data: dict) -> None:
    try:
        _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _STATE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning("Could not save Discord state: %s", e)


# guild_id -> {voice_channel_id, text_channel_id, tts_enabled, music_enabled}
# We also track voice client in memory (can't persist that)
_guild_state: dict[int, dict] = {}
_voice_clients: dict = {}  # guild_id -> VoiceClient (set by bot)
_queues: dict[int, list] = {}  # guild_id -> [{url, title}, ...]
_playing: dict[int, bool] = {}
_queue_titles: dict[int, list[str]] = {}  # for display


def get_guild_state(guild_id: int) -> dict:
    s = _guild_state.get(guild_id)
    if s:
        return s
    data = _load()
    s = data.get(str(guild_id), {}).copy()
    for k, v in _DEFAULT.items():
        if k not in s:
            s[k] = v
    _guild_state[guild_id] = s
    return s


def set_guild_state(guild_id: int, **kwargs) -> None:
    s = get_guild_state(guild_id)
    s.update(kwargs)
    _guild_state[guild_id] = s
    data = _load()
    data[str(guild_id)] = s
    _save(data)


def is_summoned(guild_id: int) -> bool:
    s = get_guild_state(guild_id)
    return bool(s.get("voice_channel_id"))


def get_voice_channel_id(guild_id: int) -> int | None:
    return get_guild_state(guild_id).get("voice_channel_id")


def get_text_channel_id(guild_id: int) -> int | None:
    return get_guild_state(guild_id).get("text_channel_id")


def tts_enabled(guild_id: int, channel_id: int | None = None) -> bool:
    s = get_guild_state(guild_id)
    if channel_id and s.get("text_channel_id") != channel_id:
        return False
    return bool(s.get("tts_enabled", True))


def music_enabled(guild_id: int) -> bool:
    return bool(get_guild_state(guild_id).get("music_enabled", True))


def set_voice_client(guild_id: int, vc) -> None:
    _voice_clients[guild_id] = vc


def get_voice_client(guild_id: int):
    return _voice_clients.get(guild_id)


def pop_voice_client(guild_id: int):
    return _voice_clients.pop(guild_id, None)


def get_queue(guild_id: int) -> list:
    return _queues.setdefault(guild_id, [])


def append_queue(guild_id: int, item: dict) -> None:
    _queues.setdefault(guild_id, []).append(item)
    _queue_titles.setdefault(guild_id, []).append(item.get("title", "?"))


def pop_queue(guild_id: int) -> dict | None:
    q = _queues.get(guild_id, [])
    if not q:
        return None
    item = q.pop(0)
    t = _queue_titles.get(guild_id, [])
    if t:
        t.pop(0)
    return item


def clear_queue(guild_id: int) -> None:
    _queues[guild_id] = []
    _queue_titles[guild_id] = []


def is_playing(guild_id: int) -> bool:
    return _playing.get(guild_id, False)


def set_playing(guild_id: int, val: bool) -> None:
    _playing[guild_id] = val


def get_queue_titles(guild_id: int) -> list[str]:
    return _queue_titles.get(guild_id, [])


# Voice-in: guild_id -> text_channel_id for sending transcript + reply
_listening: dict[int, int] = {}  # guild_id -> text_channel_id


def set_listening(guild_id: int, text_channel_id: int | None) -> None:
    if text_channel_id is None:
        _listening.pop(guild_id, None)
    else:
        _listening[guild_id] = text_channel_id


def is_listening(guild_id: int) -> bool:
    return guild_id in _listening


def get_listening_channel(guild_id: int) -> int | None:
    return _listening.get(guild_id)
