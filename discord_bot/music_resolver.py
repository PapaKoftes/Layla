"""
Resolve music from any source: YouTube, Spotify, SoundCloud, Bandcamp, direct URLs.
Uses yt-dlp (primary) and optionally spotdl for Spotify.
All sync functions are exposed via async wrappers using asyncio.to_thread.
"""
from __future__ import annotations

import asyncio
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
        import os
        import runtime_safety  # type: ignore[import]
        cfg = runtime_safety.load_config()
        cid = cfg.get("spotify_client_id") or os.environ.get("SPOTIFY_CLIENT_ID", "")
        csec = cfg.get("spotify_client_secret") or os.environ.get("SPOTIFY_CLIENT_SECRET", "")
        return (cid or "", csec or "")
    except Exception:
        import os
        return (
            os.environ.get("SPOTIFY_CLIENT_ID", ""),
            os.environ.get("SPOTIFY_CLIENT_SECRET", ""),
        )


def resolve(query: str) -> dict | None:
    """
    Resolve query to streamable URL + title.
    Returns {url, title, requester} or None on failure.
    Supports: YouTube, Spotify, SoundCloud, Bandcamp, direct URLs, search.
    """
    query = query.strip()
    if not query:
        return None

    # Spotify URL (may not start with http)
    if "spotify.com" in query or query.startswith("spotify:"):
        result = _resolve_spotify(query)
        if result:
            return result
        # Fallback: treat as search
        return _resolve_search(query)

    # Direct URL - try yt-dlp (handles YT, SoundCloud, Bandcamp, many others)
    if query.startswith(("http://", "https://")):
        return _resolve_url(query)

    # Plain search query
    return _resolve_search(query)


async def resolve_async(query: str) -> dict | None:
    """Async wrapper for resolve() — runs in thread pool to avoid blocking."""
    return await asyncio.to_thread(resolve, query)


def _resolve_url(url: str) -> dict | None:
    """Resolve URL via yt-dlp."""
    try:
        import yt_dlp  # type: ignore[import]
        opts = {
            "format": "bestaudio/best",
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
            "noplaylist": True,
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
        logger.warning("yt-dlp not installed — run: pip install yt-dlp")
        return None
    except Exception as e:
        err = str(e).lower()
        if "geo" in err or "unavailable" in err or "blocked" in err:
            logger.warning("yt-dlp: geo-blocked or unavailable: %s", e)
        elif "private" in err:
            logger.warning("yt-dlp: private video: %s", e)
        elif "deleted" in err or "removed" in err:
            logger.warning("yt-dlp: deleted/removed: %s", e)
        else:
            logger.warning("yt-dlp resolve failed: %s", e)
        return None
    return None


def _resolve_spotify(spotify_url: str) -> dict | None:
    """Resolve Spotify URL via spotdl -> YouTube URL -> stream."""
    cid, csec = _get_spotify_creds()
    if not cid or not csec:
        logger.debug("Spotify not configured; falling back to yt-dlp search")
        return None
    try:
        from spotdl import Spotdl  # type: ignore[import]
        spotdl_inst = Spotdl(client_id=cid, client_secret=csec)
        songs = spotdl_inst.search([spotify_url])
        if not songs:
            return None
        urls = spotdl_inst.get_download_urls(songs)
        if urls and urls[0]:
            return {"url": urls[0], "title": (songs[0].name or "Spotify")[:100]}
        # Fallback: get song name and search YouTube
        name = songs[0].name or ""
        if name:
            return _resolve_search(name)
    except ImportError:
        logger.debug("spotdl not installed — run: pip install spotdl")
        return None
    except Exception as e:
        logger.warning("Spotify resolve failed: %s", e)
        return None
    return None


def _resolve_search(query: str) -> dict | None:
    """Search YouTube (or general) via yt-dlp ytsearch."""
    try:
        import yt_dlp  # type: ignore[import]
        opts = {
            "format": "bestaudio/best",
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
        }
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
    except ImportError:
        logger.warning("yt-dlp not installed — run: pip install yt-dlp")
        return None
    except Exception as e:
        logger.warning("Search resolve failed for %r: %s", query, e)
        return None
    return None
