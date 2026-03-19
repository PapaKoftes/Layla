"""
Resolve music from any source: YouTube, Spotify, SoundCloud, Bandcamp, direct URLs.
Uses yt-dlp (primary) and optionally spotdl for Spotify.
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger("layla.discord")

# Add agent for config
_agent = Path(__file__).resolve().parent.parent / "agent"
import sys
if str(_agent) not in sys.path:
    sys.path.insert(0, str(_agent))


def _get_spotify_creds() -> tuple[str, str]:
    """Spotify client_id, client_secret from config or env."""
    try:
        import runtime_safety
        cfg = runtime_safety.load_config()
        cid = cfg.get("spotify_client_id") or __import__("os").environ.get("SPOTIFY_CLIENT_ID", "")
        csec = cfg.get("spotify_client_secret") or __import__("os").environ.get("SPOTIFY_CLIENT_SECRET", "")
        return (cid or "", csec or "")
    except Exception:
        return ("", "")


def resolve(query: str) -> dict | None:
    """
    Resolve query to streamable URL + title.
    Returns {url, title} or None on failure.
    Supports: YouTube, Spotify, SoundCloud, Bandcamp, direct URLs, search.
    """
    query = query.strip()
    if not query:
        return None

    # Direct URL - try yt-dlp (handles YT, SoundCloud, Bandcamp, many others)
    if query.startswith(("http://", "https://")):
        return _resolve_url(query)

    # Spotify URL - try spotdl first if configured
    if "spotify.com" in query or "spotify:" in query:
        result = _resolve_spotify(query)
        if result:
            return result
        # Fallback: search on YouTube
        return _resolve_search(query)

    # Search query
    return _resolve_search(query)


def _resolve_url(url: str) -> dict | None:
    """Resolve URL via yt-dlp."""
    try:
        import yt_dlp
        opts = {
            "format": "bestaudio/best",
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                return None
            stream_url = info.get("url")
            if not stream_url:
                for f in (info.get("formats") or [])[::-1]:
                    if f.get("url") and f.get("vcodec") == "none":
                        stream_url = f["url"]
                        break
            title = info.get("title") or info.get("id") or "Unknown"
            if stream_url:
                return {"url": stream_url, "title": title[:100]}
    except ImportError:
        logger.warning("yt-dlp not installed")
        return None
    except Exception as e:
        logger.warning("yt-dlp resolve failed: %s", e)
        return None
    return None


def _resolve_spotify(spotify_url: str) -> dict | None:
    """Resolve Spotify URL via spotdl -> YouTube URL -> stream."""
    cid, csec = _get_spotify_creds()
    if not cid or not csec:
        logger.debug("Spotify not configured; use yt-dlp search fallback")
        return None
    try:
        from spotdl import Spotdl
        spotdl = Spotdl(client_id=cid, client_secret=csec)
        songs = spotdl.search([spotify_url])
        if not songs:
            return None
        urls = spotdl.get_download_urls(songs)
        if urls and urls[0]:
            return {"url": urls[0], "title": (songs[0].name or "Spotify")[:100]}
        # Fallback: get song name and search YouTube
        name = songs[0].name or ""
        if name:
            return _resolve_search(name)
    except ImportError:
        logger.debug("spotdl not installed")
        return None
    except Exception as e:
        logger.warning("Spotify resolve failed: %s", e)
        return None
    return None


def _resolve_search(query: str) -> dict | None:
    """Search YouTube (or general) via yt-dlp."""
    try:
        import yt_dlp
        opts = {"format": "bestaudio/best", "quiet": True, "no_warnings": True}
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"ytsearch1:{query}", download=False)
            entries = info.get("entries") or []
            if not entries:
                return None
            ent = entries[0]
            url = ent.get("url")
            if not url:
                for f in (ent.get("formats") or [])[::-1]:
                    if f.get("url") and f.get("vcodec") == "none":
                        url = f["url"]
                        break
            title = ent.get("title") or ent.get("id") or query[:100]
            if url:
                return {"url": url, "title": title[:100]}
    except Exception as e:
        logger.warning("Search resolve failed: %s", e)
        return None
    return None
