from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import httpx as requests
except Exception:
    requests = None

from mutagen.flac import FLAC
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4
from mutagen.id3 import ID3, APIC, TALB, TCON, TDRC, TIT2, TPE1, TPE2, TRCK, TYER, USLT, ID3NoHeaderError


def fetch_lyrics_with_fallbacks(
    title: str,
    artist: str,
    album: str = "",
    duration_ms: int | None = None,
    platform: str = "local",
) -> Optional[str]:
    if not requests or not title:
        return None

    try:
        params = {
            "track_name": title,
            "artist_name": artist,
        }
        if album:
            params["album_name"] = album
        if duration_ms:
            params["duration"] = str(int(duration_ms / 1000))

        response = requests.get("https://lrclib.net/api/get", params=params, timeout=8)
        if response.status_code == 200:
            data = response.json()
            return data.get("syncedLyrics") or data.get("plainLyrics")
    except Exception:
        return None

    return None


def extract_featured_artists(title: str) -> tuple[str, list[str]]:
    if not title:
        return title, []

    pattern = re.compile(r"\s*(?:\(|\[)?\s*(?:feat\.?|ft\.?|featuring)\s+([^\]\)]+)", re.IGNORECASE)
    match = pattern.search(title)
    if not match:
        return title.strip(), []

    featured_chunk = match.group(1)
    featured = [a.strip() for a in re.split(r",|&| and ", featured_chunk) if a.strip()]
    clean_title = title[: match.start()].strip()
    return clean_title or title.strip(), featured


def detect_version_type(title: str, album: str) -> str:
    hay = f"{title} {album}".lower()
    keywords = {
        "remix": "remix",
        "live": "live",
        "acoustic": "acoustic",
        "cover": "cover",
        "karaoke": "karaoke",
        "instrumental": "instrumental",
    }
    for key, label in keywords.items():
        if key in hay:
            return label
    return "original"


def extract_tags_from_text(text: str) -> list[str]:
    hay = (text or "").lower()
    pool = [
        "romantic",
        "sad",
        "party",
        "dance",
        "devotional",
        "melody",
        "love",
        "hip-hop",
        "rap",
        "rock",
        "pop",
    ]
    tags = [tag for tag in pool if tag in hay]
    return list(dict.fromkeys(tags))


def has_timestamps(lyrics: str | None) -> bool:
    if not lyrics:
        return False
    return bool(re.search(r"\[\d{1,2}:\d{2}(?:\.\d+)?\]", lyrics))


def romanize_lrc_lyrics(lyrics: str | None) -> str | None:
    return lyrics


def detect_script(text: str) -> str:
    for char in text:
        code = ord(char)
        if 0x0C00 <= code <= 0x0C7F:
            return "Telugu"
        if 0x0900 <= code <= 0x097F:
            return "Devanagari"
        if 0x0980 <= code <= 0x09FF:
            return "Bengali"
        if 0x0B80 <= code <= 0x0BFF:
            return "Tamil"
        if 0x0C80 <= code <= 0x0CFF:
            return "Kannada"
        if 0x0D00 <= code <= 0x0D7F:
            return "Malayalam"
    return "Unknown"


def _extract_year(value: Any) -> str:
    if value is None:
        return ""
    raw = str(value).strip()
    if not raw:
        return ""
    m = re.search(r"(19\d{2}|20\d{2})", raw)
    return m.group(1) if m else ""


def _embed_mp3(path: Path, metadata: Dict[str, Any]) -> None:
    audio = MP3(str(path))
    if audio.tags is None:
        audio.add_tags()
    tags = audio.tags

    if metadata.get("title"):
        tags.add(TIT2(encoding=3, text=str(metadata["title"])))
    if metadata.get("artist"):
        tags.add(TPE1(encoding=3, text=str(metadata["artist"])))
    if metadata.get("album"):
        tags.add(TALB(encoding=3, text=str(metadata["album"])))
    if metadata.get("album_artist"):
        tags.add(TPE2(encoding=3, text=str(metadata["album_artist"])))
    if metadata.get("genre"):
        tags.add(TCON(encoding=3, text=str(metadata["genre"])))

    year = _extract_year(metadata.get("date") or metadata.get("release_date") or metadata.get("year"))
    if year:
        tags.add(TDRC(encoding=3, text=year))
        tags.add(TYER(encoding=3, text=year))

    track_number = metadata.get("track_number")
    if track_number:
        tags.add(TRCK(encoding=3, text=str(track_number)))

    lyrics = metadata.get("lyrics-eng") or metadata.get("lyrics")
    if lyrics:
        tags.add(USLT(encoding=3, lang="eng", desc="", text=str(lyrics)))

    audio.save(v2_version=3)


def _embed_flac(path: Path, metadata: Dict[str, Any]) -> None:
    audio = FLAC(path)
    if metadata.get("title"):
        audio["title"] = [str(metadata["title"])]
    if metadata.get("artist"):
        audio["artist"] = [str(metadata["artist"])]
    if metadata.get("album"):
        audio["album"] = [str(metadata["album"])]
    if metadata.get("album_artist"):
        audio["albumartist"] = [str(metadata["album_artist"])]
    if metadata.get("genre"):
        audio["genre"] = [str(metadata["genre"])]

    year = _extract_year(metadata.get("date") or metadata.get("release_date") or metadata.get("year"))
    if year:
        audio["date"] = [year]

    track_number = metadata.get("track_number")
    if track_number:
        audio["tracknumber"] = [str(track_number)]

    lyrics = metadata.get("lyrics-eng") or metadata.get("lyrics")
    if lyrics:
        audio["lyrics"] = [str(lyrics)]

    audio.save()


def _embed_m4a(path: Path, metadata: Dict[str, Any]) -> None:
    audio = MP4(path)
    if metadata.get("title"):
        audio["\xa9nam"] = [str(metadata["title"])]
    if metadata.get("artist"):
        audio["\xa9ART"] = [str(metadata["artist"])]
    if metadata.get("album"):
        audio["\xa9alb"] = [str(metadata["album"])]
    if metadata.get("album_artist"):
        audio["aART"] = [str(metadata["album_artist"])]
    if metadata.get("genre"):
        audio["\xa9gen"] = [str(metadata["genre"])]

    year = _extract_year(metadata.get("date") or metadata.get("release_date") or metadata.get("year"))
    if year:
        audio["\xa9day"] = [year]

    track_number = metadata.get("track_number")
    if track_number:
        audio["trkn"] = [(int(track_number), 0)]

    lyrics = metadata.get("lyrics-eng") or metadata.get("lyrics")
    if lyrics:
        audio["\xa9lyr"] = [str(lyrics)]

    audio.save()


def embed_metadata(file_path: str | Path, metadata: Dict[str, Any]) -> None:
    path = Path(file_path)
    suffix = path.suffix.lower()
    if suffix == ".mp3":
        _embed_mp3(path, metadata)
    elif suffix == ".flac":
        _embed_flac(path, metadata)
    elif suffix in {".m4a", ".mp4", ".aac"}:
        _embed_m4a(path, metadata)


def query_musicbrainz_fuzzy(title: str, artist: str = "") -> Optional[Dict[str, Any]]:
    try:
        import musicbrainzngs as mb
        mb.set_useragent("MetadataTools", "1.0")
        result = mb.search_recordings(artist=artist, recording=title, limit=5)
        recs = result.get("recording-list") or []
        if not recs:
            return None

        best = max(recs, key=lambda item: int(item.get("ext:score", 0)))
        if int(best.get("ext:score", 0)) < 60:
            return None

        mbid = best.get("id")
        if not mbid:
            return None

        return query_musicbrainz_by_id(mbid)
    except Exception:
        return None


def query_musicbrainz_by_id(mbid: str) -> Optional[Dict[str, Any]]:
    try:
        import musicbrainzngs as mb
        mb.set_useragent("MetadataTools", "1.0")
        data = mb.get_recording_by_id(mbid, includes=["artists", "releases", "tags"])
        rec = (data or {}).get("recording") or {}
        rel_list = rec.get("release-list") or []
        release = rel_list[0] if rel_list else {}

        genre = None
        tags = rec.get("tag-list") or []
        if tags:
            genre = ", ".join([t.get("name") for t in tags[:3] if t.get("name")]) or None

        release_date = release.get("date") or rec.get("first-release-date")

        return {
            "mbid": mbid,
            "title": rec.get("title"),
            "artist": rec.get("artist-credit-phrase", ""),
            "album": release.get("title"),
            "release_date": release_date,
            "genre": genre,
            "track_number": None,
            "isrc": None,
            "method": "musicbrainz_by_id",
            "confidence": 0.8,
        }
    except Exception:
        return None
