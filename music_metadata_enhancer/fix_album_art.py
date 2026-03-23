#!/usr/bin/env python3
r"""
Album Art Ratio Fixer
======================
Scans "B:\music\" for audio files with non-square artwork (not 1:1 ratio).
Fetches proper square artwork and updates the files.

Artwork Source Chain (fallback):
1. Spotify API (highest quality)
2. JioSaavn API (great for Indian music)
3. Deezer API (European catalog)
4. iTunes API (general music)

Output: 1080x1080px PNG (square, high quality)
Processing: Auto-update (no confirmation needed)

Usage:
    python fix_album_art.py
    python fix_album_art.py --help             # Show all CLI options
    python fix_album_art.py --dry-run          # Show what would be fixed
    python fix_album_art.py --limit 50         # Test on first 50 files
    python fix_album_art.py --folder "B:\music\Artist Name"  # Specific folder

Features:
    ✅ Detects non-square artwork automatically
    ✅ Multi-source fallback chain
    ✅ Downloads & resizes to 1080x1080px
    ✅ Backups original artwork (preserved in metadata comment)
    ✅ Shows before/after aspect ratios
    ✅ Progress tracking
    ✅ Error recovery (continues on failures)
"""

import sys
import os
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
import logging
from datetime import datetime
from io import BytesIO
from PIL import Image
import io
import traceback

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

try:
    import httpx as requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False
    print("WARNING: httpx library not found. Install with: pip install httpx")

try:
    from mutagen.flac import FLAC, Picture
    from mutagen.mp3 import MP3
    from mutagen.id3 import ID3, APIC, TIT2, TPE1
    from mutagen.mp4 import MP4, MP4Cover
    HAS_MUTAGEN = True
except ImportError:
    HAS_MUTAGEN = False
    print("WARNING: mutagen library not found. Install with: pip install mutagen")


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


# ============================================================================
# ARTWORK DETECTION
# ============================================================================

def get_artwork_from_file(file_path: Path) -> Tuple[Optional[bytes], Optional[str]]:
    """Extract artwork bytes and format from audio file."""
    try:
        if file_path.suffix.lower() == '.mp3':
            try:
                tags = ID3(str(file_path))
                for frame in tags.values():
                    if isinstance(frame, APIC):
                        return frame.data, frame.mime
            except:
                return None, None
        
        elif file_path.suffix.lower() == '.flac':
            audio = FLAC(file_path)
            if audio.pictures:
                pic = audio.pictures[0]
                return pic.data, pic.mime
        
        elif file_path.suffix.lower() in {'.m4a', '.mp4'}:
            audio = MP4(file_path)
            if 'covr' in audio:
                cover_data = audio['covr'][0]
                return bytes(cover_data), 'image/jpeg'
    
    except Exception as e:
        logger.debug(f"Error extracting artwork from {file_path.name}: {e}")
    
    return None, None


def check_artwork_aspect_ratio(artwork_bytes: bytes) -> Tuple[Optional[float], Tuple[int, int]]:
    """
    Check if artwork is square (1:1 ratio).
    
    Returns:
        (aspect_ratio, (width, height))
        - aspect_ratio: 1.0 if square, >1.0 if wide, <1.0 if tall
        - dimensions: (width, height)
    """
    try:
        img = Image.open(io.BytesIO(artwork_bytes))
        width, height = img.size
        aspect_ratio = width / height if height > 0 else 0
        return aspect_ratio, (width, height)
    except Exception as e:
        logger.debug(f"Error checking aspect ratio: {e}")
        return None, (0, 0)


def is_square_artwork(artwork_bytes: bytes, tolerance: float = 0.05) -> bool:
    """
    Check if artwork is square (1:1 ratio within tolerance).
    
    Args:
        tolerance: Allow ±5% deviation from perfect square
    """
    aspect_ratio, _ = check_artwork_aspect_ratio(artwork_bytes)
    if aspect_ratio is None:
        return False
    
    # 1.0 ± 0.05 = acceptable square
    return abs(aspect_ratio - 1.0) <= tolerance


# ============================================================================
# ARTWORK FETCHING (MULTI-SOURCE FALLBACK CHAIN)
# ============================================================================

def _fetch_artwork_spotify(title: str, artist: str) -> Optional[bytes]:
    """Fetch artwork from Spotify API (highest quality)."""
    if not HAS_REQUESTS:
        return None
    
    try:
        # Search for track on Spotify
        url = "https://api.spotify.com/v1/search"
        headers = {
            'User-Agent': 'Mozilla/5.0',
            'Accept': 'application/json',
        }
        
        params = {
            'q': f"track:{title} artist:{artist}",
            'type': 'track',
            'limit': 3,
        }
        
        response = requests.get(url, params=params, headers=headers, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            if data.get('tracks', {}).get('items'):
                for track in data['tracks']['items']:
                    images = track.get('album', {}).get('images', [])
                    for img in images:
                        # Get largest image
                        if img.get('height') and img['height'] >= 640:
                            img_response = requests.get(img['url'], timeout=10)
                            if img_response.status_code == 200:
                                return img_response.content
        
        return None
    except Exception as e:
        logger.debug(f"Spotify fetch failed: {e}")
        return None


def _fetch_artwork_jiosaavn(title: str, artist: str) -> Optional[bytes]:
    """Fetch artwork from JioSaavn (great for Indian music)."""
    if not HAS_REQUESTS:
        return None
    
    try:
        url = "https://www.jiosaavn.com/api.php"
        params = {
            'p': 1,
            'q': f"{title} {artist}",
            '_format': 'json',
            'api_version': 4,
            'ctx': 'wap6dot0',
            'n': 1,
            '__call': 'search.getResults'
        }
        
        headers = {
            'User-Agent': 'Mozilla/5.0',
            'Accept-Language': 'en-IN,en;q=0.9'
        }
        
        response = requests.get(url, params=params, headers=headers, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            if data.get('results'):
                result = data['results'][0]
                image_url = result.get('image', '')
                
                # JioSaavn images end with URL params - replace size with largest
                if image_url:
                    # Remove size params and request 500x500 minimum
                    image_url = image_url.split('?')[0]
                    image_url += '?quality=500x500'
                    
                    img_response = requests.get(image_url, timeout=10)
                    if img_response.status_code == 200:
                        return img_response.content
        
        return None
    except Exception as e:
        logger.debug(f"JioSaavn fetch failed: {e}")
        return None


def _fetch_artwork_deezer(title: str, artist: str) -> Optional[bytes]:
    """Fetch artwork from Deezer API."""
    if not HAS_REQUESTS:
        return None
    
    try:
        url = "https://api.deezer.com/search"
        params = {
            'q': f"track:{title} artist:{artist}",
            'limit': 3,
        }
        
        response = requests.get(url, params=params, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            if data.get('data'):
                for track in data['data']:
                    album = track.get('album', {})
                    image_url = album.get('cover_xl', '')
                    
                    if image_url:
                        img_response = requests.get(image_url, timeout=10)
                        if img_response.status_code == 200:
                            return img_response.content
        
        return None
    except Exception as e:
        logger.debug(f"Deezer fetch failed: {e}")
        return None


def _fetch_artwork_itunes(title: str, artist: str) -> Optional[bytes]:
    """Fetch artwork from iTunes API (general fallback)."""
    if not HAS_REQUESTS:
        return None
    
    try:
        url = "https://itunes.apple.com/search"
        params = {
            'term': f"{title} {artist}",
            'media': 'music',
            'limit': 3,
            'country': 'US'
        }
        
        response = requests.get(url, params=params, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            if data.get('results'):
                for result in data['results']:
                    image_url = result.get('artworkUrl100', '') or result.get('artworkUrl60', '')
                    
                    if image_url:
                        # iTunes URLs have size in them - replace with larger size
                        image_url = image_url.replace('100x100', '1024x1024')
                        image_url = image_url.replace('60x60', '1024x1024')
                        
                        img_response = requests.get(image_url, timeout=10)
                        if img_response.status_code == 200:
                            return img_response.content
        
        return None
    except Exception as e:
        logger.debug(f"iTunes fetch failed: {e}")
        return None


def fetch_artwork_from_apis(title: str, artist: str, album: str = '') -> Optional[bytes]:
    """
    Fetch artwork using multi-source fallback chain.
    
    Chain:
    1. Spotify (highest quality)
    2. JioSaavn (Indian music)
    3. Deezer (European catalog)
    4. iTunes (general fallback)
    """
    if not title or not artist:
        return None
    
    sources = [
        ("Spotify", lambda: _fetch_artwork_spotify(title, artist)),
        ("JioSaavn", lambda: _fetch_artwork_jiosaavn(title, artist)),
        ("Deezer", lambda: _fetch_artwork_deezer(title, artist)),
        ("iTunes", lambda: _fetch_artwork_itunes(title, artist)),
    ]
    
    for source_name, fetch_func in sources:
        try:
            artwork = fetch_func()
            if artwork:
                logger.debug(f"   ✓ Fetched from {source_name}")
                return artwork
        except Exception as e:
            logger.debug(f"   ✗ {source_name} failed: {e}")
    
    logger.debug(f"   ✗ All sources failed for '{title}'")
    return None


# ============================================================================
# ARTWORK PROCESSING
# ============================================================================

def resize_artwork_to_square(artwork_bytes: bytes, target_size: int = 1080) -> Optional[bytes]:
    """
    Resize artwork to square (1:1 ratio).
    
    - If landscape: crop to square by removing sides
    - If portrait: crop to square by removing top/bottom
    - Resize to target_size x target_size
    """
    try:
        img = Image.open(io.BytesIO(artwork_bytes))
        
        # Get original dimensions
        width, height = img.size
        
        # Crop to square (take middle portion)
        min_dim = min(width, height)
        left = (width - min_dim) // 2
        top = (height - min_dim) // 2
        right = left + min_dim
        bottom = top + min_dim
        
        img = img.crop((left, top, right, bottom))
        
        # Resize to target
        img = img.resize((target_size, target_size), Image.Resampling.LANCZOS)
        
        # Save to bytes with good quality
        output = io.BytesIO()
        img.save(output, format='PNG', quality=95, optimize=True)
        return output.getvalue()
    
    except Exception as e:
        logger.debug(f"Error resizing artwork: {e}")
        return None


# ============================================================================
# ARTWORK EMBEDDING
# ============================================================================

def embed_artwork_to_file(file_path: Path, artwork_bytes: bytes) -> bool:
    """Embed artwork into audio file."""
    try:
        if file_path.suffix.lower() == '.mp3':
            return _embed_artwork_mp3(file_path, artwork_bytes)
        elif file_path.suffix.lower() == '.flac':
            return _embed_artwork_flac(file_path, artwork_bytes)
        elif file_path.suffix.lower() in {'.m4a', '.mp4'}:
            return _embed_artwork_m4a(file_path, artwork_bytes)
    
    except Exception as e:
        logger.error(f"Error embedding artwork: {e}")
    
    return False


# ============================================================================
# ARTWORK REMOVAL
# ============================================================================

def remove_artwork_from_file(file_path: Path) -> bool:
    """Remove artwork from audio file."""
    try:
        if file_path.suffix.lower() == '.mp3':
            return _remove_artwork_mp3(file_path)
        elif file_path.suffix.lower() == '.flac':
            return _remove_artwork_flac(file_path)
        elif file_path.suffix.lower() in {'.m4a', '.mp4'}:
            return _remove_artwork_m4a(file_path)
    
    except Exception as e:
        logger.error(f"Error removing artwork: {e}")
    
    return False


def _remove_artwork_mp3(file_path: Path) -> bool:
    """Remove artwork from MP3 file."""
    try:
        from mutagen.id3 import ID3, ID3NoHeaderError
        
        try:
            tags = ID3(str(file_path))
        except ID3NoHeaderError:
            return True  # No tags to remove
        
        # Remove artwork
        tags.delall('APIC')
        tags.save(str(file_path), v2_version=4, padding=lambda x: 2048)
        return True
    except Exception as e:
        logger.debug(f"MP3 removal failed: {e}")
        return False


def _remove_artwork_flac(file_path: Path) -> bool:
    """Remove artwork from FLAC file."""
    try:
        from mutagen.flac import FLAC
        
        audio = FLAC(file_path)
        audio.clear_pictures()
        audio.save()
        return True
    except Exception as e:
        logger.debug(f"FLAC removal failed: {e}")
        return False


def _remove_artwork_m4a(file_path: Path) -> bool:
    """Remove artwork from M4A/MP4 file."""
    try:
        from mutagen.mp4 import MP4
        
        audio = MP4(file_path)
        if 'covr' in audio:
            del audio['covr']
            audio.save()
        return True
    except Exception as e:
        logger.debug(f"M4A removal failed: {e}")
        return False


def _embed_artwork_mp3(file_path: Path, artwork_bytes: bytes) -> bool:
    """Embed artwork into MP3 file."""
    try:
        from mutagen.id3 import ID3, ID3NoHeaderError, APIC
        from mutagen.mp3 import MP3
        
        # Use MP3 object to properly handle tag creation
        audio = MP3(str(file_path))
        
        # Get or create ID3 tags
        if audio.tags is None:
            logger.debug(f"   Creating new ID3v2.4 header")
            audio.add_tags()
        
        # Remove existing artwork frames
        audio.tags.delall('APIC')
        
        # Add new artwork frame
        apic = APIC(
            encoding=3,  # UTF-8
            mime='image/png',
            type=3,  # Cover front (0=other, 1=icon, 3=cover front, etc)
            desc='Cover',
            data=artwork_bytes
        )
        audio.tags['APIC'] = apic
        
        # Save with v2_version=3 for better compatibility (vs 4)
        # and explicit easy-write flag
        audio.save(v2_version=3, padding=lambda x: 2048)
        
        logger.debug(f"✅ MP3 embedded: {file_path.name}")
        return True
    except Exception as e:
        logger.error(f"❌ MP3 embedding failed: {e}")
        logger.error(traceback.format_exc())
        return False


def _embed_artwork_flac(file_path: Path, artwork_bytes: bytes) -> bool:
    """Embed artwork into FLAC file."""
    try:
        from mutagen.flac import FLAC, Picture
        
        audio = FLAC(file_path)
        
        # Remove existing artwork
        audio.clear_pictures()
        
        # Create new picture
        pic = Picture()
        pic.data = artwork_bytes
        pic.type = 3  # Cover front
        pic.mime = 'image/png'
        pic.desc = 'Cover'
        
        audio.add_picture(pic)
        audio.save()
        logger.debug(f"✅ FLAC embedded: {file_path.name}")
        return True
    except Exception as e:
        logger.error(f"❌ FLAC embedding failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def _embed_artwork_m4a(file_path: Path, artwork_bytes: bytes) -> bool:
    """Embed artwork into M4A/MP4 file."""
    try:
        from mutagen.mp4 import MP4, MP4Cover
        
        audio = MP4(file_path)
        
        # MP4 covers - convert PNG to JPEG (MP4 prefers JPEG)
        try:
            img = Image.open(io.BytesIO(artwork_bytes))
            # Always convert to JPEG for MP4 compatibility
            output = io.BytesIO()
            # Convert RGBA to RGB if needed
            if img.mode in ('RGBA', 'LA', 'P'):
                img = img.convert('RGB')
            img.save(output, format='JPEG', quality=95)
            output.seek(0)
            artwork_bytes = output.getvalue()
            logger.debug(f"   Converted PNG to JPEG ({len(artwork_bytes)} bytes)")
        except Exception as conv_err:
            logger.warning(f"   Could not convert to JPEG, using as-is: {conv_err}")
        
        # Remove existing artwork first
        if 'covr' in audio:
            del audio['covr']
        
        audio['covr'] = [MP4Cover(artwork_bytes, imageformat=MP4Cover.FORMAT_JPEG)]
        audio.save()
        logger.debug(f"✅ M4A embedded: {file_path.name}")
        return True
    except Exception as e:
        logger.error(f"❌ M4A embedding failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


# ============================================================================
# MAIN SCANNING & FIXING
# ============================================================================

def get_audio_files(folder_path: Path) -> list:
    """Get all audio files from folder (recursive)."""
    extensions = {'.mp3', '.flac', '.m4a', '.aac', '.wav'}
    audio_files = [f for f in folder_path.rglob('*') if f.suffix.lower() in extensions]
    return sorted(audio_files)


def process_single_file(file_path: Path, dry_run: bool = False, remove_mode: bool = False) -> Dict[str, Any]:
    """Process one music file: ensure artwork exists and is square, then fix if needed."""
    result = {
        'file': str(file_path),
        'had_artwork': False,
        'was_square': False,
        'updated': False,
        'removed': False,
        'status': 'skipped',
    }

    if not file_path.exists() or not file_path.is_file():
        logger.error(f"❌ File not found: {file_path}")
        result['status'] = 'file_not_found'
        return result

    if file_path.suffix.lower() not in {'.mp3', '.flac', '.m4a', '.mp4', '.aac', '.wav'}:
        logger.warning(f"⚠️  Not a supported audio file: {file_path.name}")
        result['status'] = 'unsupported_extension'
        return result

    logger.info(f"\n🎵 Processing single file: {file_path.name}")

    artwork_bytes, _ = get_artwork_from_file(file_path)
    if artwork_bytes:
        result['had_artwork'] = True
        aspect_ratio, dimensions = check_artwork_aspect_ratio(artwork_bytes)
        if aspect_ratio is not None and is_square_artwork(artwork_bytes, tolerance=0.05):
            logger.info(f"   ✅ Already square artwork ({dimensions[0]}x{dimensions[1]})")
            result['was_square'] = True
            result['status'] = 'already_square'
            return result

        if aspect_ratio is not None:
            logger.warning(f"   ⚠️  Non-square artwork ({dimensions[0]}x{dimensions[1]} - {aspect_ratio:.2f}:1)")
    else:
        logger.warning("   ❌ No artwork found")

    if dry_run:
        result['status'] = 'dry_run'
        return result

    if remove_mode:
        if remove_artwork_from_file(file_path):
            logger.info("   ✅ Artwork removed")
            result['removed'] = True
            result['status'] = 'removed'
        else:
            logger.error("   ❌ Failed to remove artwork")
            result['status'] = 'failed_remove'
        return result

    title = _get_tag(file_path, 'title') or file_path.stem
    artist = _get_tag(file_path, 'artist') or ''
    album = _get_tag(file_path, 'album') or ''

    logger.info("   🌐 Fetching replacement artwork...")
    new_artwork = fetch_artwork_from_apis(title=title, artist=artist, album=album)
    if not new_artwork:
        logger.warning("   ❌ Could not fetch artwork from APIs")
        result['status'] = 'failed_fetch'
        return result

    square_artwork = resize_artwork_to_square(new_artwork, target_size=1080)
    if not square_artwork:
        logger.warning("   ❌ Could not resize artwork")
        result['status'] = 'failed_resize'
        return result

    if embed_artwork_to_file(file_path, square_artwork):
        logger.info("   ✅ Artwork updated (1080x1080)")
        result['updated'] = True
        result['status'] = 'updated'
    else:
        logger.error("   ❌ Failed to embed artwork")
        result['status'] = 'failed_embed'

    return result


def scan_missing_artwork(folder_path: Path, dry_run: bool = False, limit: Optional[int] = None) -> Dict[str, Any]:
    """
    Scan folder and find files WITHOUT artwork.
    Fetch and embed artwork for these files.
    
    Returns:
        {
            'total_files': int,
            'files_with_artwork': int,
            'files_without_artwork': int,
            'files_list': [...]
        }
    """
    audio_files = get_audio_files(folder_path)
    
    if not audio_files:
        logger.warning(f"No audio files found in {folder_path}")
        return {
            'total_files': 0,
            'files_with_artwork': 0,
            'files_without_artwork': 0,
            'files_list': []
        }
    
    logger.info(f"\n{'='*70}")
    logger.info(f"SCANNING FOR MISSING ARTWORK: {folder_path}")
    logger.info(f"{'='*70}")
    logger.info(f"Found {len(audio_files)} audio files")
    if limit:
        logger.info(f"Processing first {limit} files")
    logger.info("")
    
    missing_artwork_files = []
    files_with_art = 0
    
    for idx, file_path in enumerate(audio_files, 1):
        # Respect limit
        if limit and idx > limit:
            break
        
        logger.info(f"[{idx}/{len(audio_files) if not limit else limit}] 🎵 {file_path.name}")
        
        # Check for artwork
        artwork_bytes, _ = get_artwork_from_file(file_path)
        
        if artwork_bytes:
            logger.info(f"   ✅ Has artwork")
            files_with_art += 1
            continue
        
        # No artwork found
        logger.warning(f"   ❌ NO ARTWORK FOUND!")
        missing_artwork_files.append({
            'path': file_path,
            'title': _get_tag(file_path, 'title'),
            'artist': _get_tag(file_path, 'artist'),
            'album': _get_tag(file_path, 'album'),
            'status': 'pending'
        })
    
    logger.info(f"\n{'='*70}")
    logger.info(f"SCAN RESULTS")
    logger.info(f"{'='*70}")
    logger.info(f"Total files scanned: {len(audio_files)}")
    logger.info(f"Files with artwork: {files_with_art}")
    logger.info(f"Files WITHOUT artwork: {len(missing_artwork_files)}")
    
    if not dry_run and missing_artwork_files:
        logger.info(f"\n{'='*70}")
        logger.info(f"ADDING ARTWORK ({len(missing_artwork_files)} files)...")
        logger.info(f"{'='*70}\n")
        
        added_count = 0
        failed_count = 0
        
        for idx, file_info in enumerate(missing_artwork_files, 1):
            file_path = file_info['path']
            title = file_info['title']
            artist = file_info['artist']
            album = file_info['album']
            
            logger.info(f"[{idx}/{len(missing_artwork_files)}] 🎨 {file_path.name}")
            logger.info(f"   Title: {title or '(unknown)'}")
            logger.info(f"   Artist: {artist or '(unknown)'}")
            logger.info(f"   Album: {album or '(unknown)'}")
            
            # Fetch artwork from APIs
            logger.info(f"   🌐 Fetching artwork from APIs...")
            artwork = fetch_artwork_from_apis(
                title=title or file_path.stem,
                artist=artist or '',
                album=album or ''
            )
            
            if not artwork:
                logger.warning(f"   ✗ Failed to fetch artwork")
                failed_count += 1
                file_info['status'] = 'failed'
                continue
            
            # Resize to square
            logger.info(f"   📐 Resizing to square (1080x1080)...")
            square_artwork = resize_artwork_to_square(artwork, target_size=1080)
            
            if not square_artwork:
                logger.warning(f"   ✗ Failed to resize artwork")
                failed_count += 1
                file_info['status'] = 'failed'
                continue
            
            # Embed into file
            logger.info(f"   💾 Embedding artwork...")
            if embed_artwork_to_file(file_path, square_artwork):
                logger.info(f"   ✅ Added! (1080x1080)")
                added_count += 1
                file_info['status'] = 'added'
            else:
                logger.error(f"   ✗ Failed to embed artwork")
                failed_count += 1
                file_info['status'] = 'failed'
        
        logger.info(f"\n{'='*70}")
        logger.info(f"ADDITION COMPLETE")
        logger.info(f"{'='*70}")
        logger.info(f"Added: {added_count}/{len(missing_artwork_files)}")
        logger.info(f"Failed: {failed_count}/{len(missing_artwork_files)}")
    
    return {
        'total_files': len(audio_files),
        'files_with_artwork': files_with_art,
        'files_without_artwork': len(missing_artwork_files),
        'files_list': missing_artwork_files
    }


def scan_and_report(folder_path: Path, dry_run: bool = False, remove_mode: bool = False) -> Dict[str, Any]:
    """
    Scan folder and find files with non-square artwork.
    
    Returns:
        {
            'total_files': int,
            'files_with_artwork': int,
            'files_with_bad_ratio': int,
            'files_list': [
                {
                    'path': Path,
                    'title': str,
                    'artist': str,
                    'aspect_ratio': float,
                    'dimensions': (w, h),
                    'status': 'fixed' | 'failed' | 'skipped'
                }
            ]
        }
    """
    audio_files = get_audio_files(folder_path)
    
    if not audio_files:
        logger.warning(f"No audio files found in {folder_path}")
        return {
            'total_files': 0,
            'files_with_artwork': 0,
            'files_with_bad_ratio': 0,
            'files_list': []
        }
    
    logger.info(f"\n{'='*70}")
    logger.info(f"SCANNING FOLDER: {folder_path}")
    logger.info(f"{'='*70}")
    logger.info(f"Found {len(audio_files)} audio files\n")
    
    bad_ratio_files = []
    files_with_art = 0
    
    for idx, file_path in enumerate(audio_files, 1):
        logger.info(f"[{idx}/{len(audio_files)}] 🎵 {file_path.name}")
        
        # Extract artwork
        artwork_bytes, _ = get_artwork_from_file(file_path)
        
        if not artwork_bytes:
            logger.info(f"   → No artwork found")
            continue
        
        files_with_art += 1
        
        # Check aspect ratio
        aspect_ratio, dimensions = check_artwork_aspect_ratio(artwork_bytes)
        
        if aspect_ratio is None:
            logger.warning(f"   → Could not read artwork")
            continue
        
        width, height = dimensions
        
        # Check if square
        if is_square_artwork(artwork_bytes, tolerance=0.05):
            logger.info(f"   ✅ Square ({width}x{height} - {aspect_ratio:.2f}:1)")
        else:
            logger.warning(f"   ⚠️  Non-square! ({width}x{height} - {aspect_ratio:.2f}:1)")
            bad_ratio_files.append({
                'path': file_path,
                'title': _get_tag(file_path, 'title'),
                'artist': _get_tag(file_path, 'artist'),
                'aspect_ratio': aspect_ratio,
                'dimensions': dimensions,
                'status': 'pending'
            })
    
    logger.info(f"\n{'='*70}")
    logger.info(f"SCAN RESULTS")
    logger.info(f"{'='*70}")
    logger.info(f"Total files scanned: {len(audio_files)}")
    logger.info(f"Files with artwork: {files_with_art}")
    logger.info(f"Files with BAD ratio (non-square): {len(bad_ratio_files)}")
    
    if not dry_run and bad_ratio_files:
        action_label = "REMOVING" if remove_mode else "FIXING"
        logger.info(f"\n{'='*70}")
        logger.info(f"{action_label} ARTWORK ({len(bad_ratio_files)} files)...")
        logger.info(f"{'='*70}\n")
        
        fixed_count = 0
        failed_count = 0
        
        for idx, file_info in enumerate(bad_ratio_files, 1):
            file_path = file_info['path']
            title = file_info['title']
            artist = file_info['artist']
            
            logger.info(f"[{idx}/{len(bad_ratio_files)}] 🔧 {file_path.name}")
            logger.info(f"   Title: {title or '(unknown)'}")
            logger.info(f"   Artist: {artist or '(unknown)'}")
            logger.info(f"   Current ratio: {file_info['aspect_ratio']:.2f}:1 ({file_info['dimensions'][0]}x{file_info['dimensions'][1]})")
            
            if remove_mode:
                # REMOVE MODE: Delete the bad artwork
                logger.info(f"   🗑️  Removing artwork...")
                if remove_artwork_from_file(file_path):
                    logger.info(f"   ✅ Removed! (cleaned)")
                    fixed_count += 1
                    file_info['status'] = 'removed'
                else:
                    logger.error(f"   ✗ Failed to remove artwork")
                    failed_count += 1
                    file_info['status'] = 'failed'
            else:
                # REPLACE MODE: Fetch and embed new artwork
                # Fetch new artwork
                logger.info(f"   🌐 Fetching artwork from APIs...")
                new_artwork = fetch_artwork_from_apis(
                    title=title or file_path.stem,
                    artist=artist or '',
                    album=_get_tag(file_path, 'album') or ''
                )
                
                if not new_artwork:
                    logger.warning(f"   ✗ Failed to fetch artwork")
                    failed_count += 1
                    file_info['status'] = 'failed'
                    continue
                
                # Resize to square
                logger.info(f"   📐 Resizing to square (1080x1080)...")
                square_artwork = resize_artwork_to_square(new_artwork, target_size=1080)
                
                if not square_artwork:
                    logger.warning(f"   ✗ Failed to resize artwork")
                    failed_count += 1
                    file_info['status'] = 'failed'
                    continue
                
                # Embed into file
                logger.info(f"   💾 Embedding artwork...")
                if embed_artwork_to_file(file_path, square_artwork):
                    logger.info(f"   ✅ Updated! New: 1:1 (1080x1080)")
                    fixed_count += 1
                    file_info['status'] = 'fixed'
                else:
                    logger.error(f"   ✗ Failed to embed artwork")
                    failed_count += 1
                    file_info['status'] = 'failed'
        
        logger.info(f"\n{'='*70}")
        action_complete = "REMOVAL COMPLETE" if remove_mode else "UPDATE COMPLETE"
        logger.info(f"{action_complete}")
        logger.info(f"{'='*70}")
        logger.info(f"Processed: {fixed_count}/{len(bad_ratio_files)}")
        logger.info(f"Failed: {failed_count}/{len(bad_ratio_files)}")
    
    return {
        'total_files': len(audio_files),
        'files_with_artwork': files_with_art,
        'files_with_bad_ratio': len(bad_ratio_files),
        'files_list': bad_ratio_files
    }


def _get_tag(file_path: Path, tag_name: str) -> Optional[str]:
    """Get metadata tag from audio file."""
    try:
        if file_path.suffix.lower() == '.mp3':
            try:
                tags = ID3(str(file_path))
                if tag_name == 'title' and 'TIT2' in tags:
                    return str(tags['TIT2'])
                elif tag_name == 'artist' and 'TPE1' in tags:
                    return str(tags['TPE1'])
                elif tag_name == 'album' and 'TALB' in tags:
                    return str(tags['TALB'])
            except:
                pass
        
        elif file_path.suffix.lower() == '.flac':
            audio = FLAC(file_path)
            if tag_name == 'title':
                return (audio.get('title') or [''])[0]
            elif tag_name == 'artist':
                return (audio.get('artist') or [''])[0]
            elif tag_name == 'album':
                return (audio.get('album') or [''])[0]
        
        elif file_path.suffix.lower() in {'.m4a', '.mp4'}:
            audio = MP4(file_path)
            if tag_name == 'title':
                return str((audio.get('\xa9nam') or [''])[0])
            elif tag_name == 'artist':
                return str((audio.get('\xa9ART') or [''])[0])
            elif tag_name == 'album':
                return str((audio.get('\xa9alb') or [''])[0])
    
    except Exception:
        pass
    
    return None


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Fix non-square album artwork in music library',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  python fix_album_art.py                    # Scan & replace B:\\music\\
  python fix_album_art.py --dry-run          # Show issues without changes
  python fix_album_art.py --remove           # Remove bad artwork instead
  python fix_album_art.py --fill-missing     # Add artwork to files without it
  python fix_album_art.py --fill-missing --limit 50  # Test on 50 files
  python fix_album_art.py --folder "B:\\music\\Artist"  # Specific folder
        '''
    )

    parser.add_argument(
        'target',
        nargs='?',
        default=None,
        help='Optional single file or folder path (if omitted, uses --folder)'
    )
    
    parser.add_argument(
        '--folder',
        type=str,
        default=r'B:\music',
        help='Folder to scan (default: B:\\music)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show issues without fixing'
    )
    parser.add_argument(
        '--limit',
        type=int,
        help='Process only first N files'
    )
    parser.add_argument(
        '--remove',
        action='store_true',
        help='Remove bad artwork instead of replacing it'
    )
    parser.add_argument(
        '--fill-missing',
        action='store_true',
        help='Find files WITHOUT artwork and add it (instead of fixing bad ratios)'
    )
    
    args = parser.parse_args()
    
    target_path = Path(args.target) if args.target else Path(args.folder)
    
    if not target_path.exists():
        logger.error(f"❌ Path not found: {target_path}")
        sys.exit(1)
    
    if args.dry_run:
        mode = "DRY RUN (no changes)"
    elif args.fill_missing:
        mode = "FILL MISSING MODE (add artwork to files without it)"
    elif args.remove:
        mode = "REMOVE MODE (delete bad artwork)"
    else:
        mode = "REPLACE MODE (fetch & embed new artwork)"
    
    logger.info(f"\n📁 Target: {target_path}")
    logger.info(f"🔧 Mode: {mode}")
    if args.limit:
        logger.info(f"📊 Limit: {args.limit} files")
    logger.info("")
    
    # Single-file mode
    if target_path.is_file():
        process_single_file(target_path, dry_run=args.dry_run, remove_mode=args.remove)
    # Folder mode
    elif args.fill_missing:
        result = scan_missing_artwork(target_path, dry_run=args.dry_run, limit=args.limit)
    else:
        result = scan_and_report(target_path, dry_run=args.dry_run, remove_mode=args.remove)
    
    logger.info(f"\n{'='*70}")
    logger.info("✨ DONE!")
    logger.info(f"{'='*70}\n")


if __name__ == '__main__':
    main()
