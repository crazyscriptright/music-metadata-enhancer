#!/usr/bin/env python3
"""
Picard Fallback Enricher (Refactored)
=====================================
Uses shared API clients + Picard's underlying libraries (musicbrainzngs + AcoustID) 
as fallback when primary enrichment is incomplete.

Features:
- AcoustID fingerprinting (identifies song even if tags are wrong)
- MusicBrainz fuzzy matching + comprehensive metadata via shared client
- Automatic genre, release date, ISRC fetching
- Duplicate detection

Only runs if primary enrichment is missing critical fields.
"""

import logging
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Optional, Dict, Any

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

try:
    import musicbrainzngs as mb
    HAS_MUSICBRAINZ = True
except ImportError:
    HAS_MUSICBRAINZ = False

try:
    import acoustid
    HAS_ACOUSTID = True
except ImportError:
    try:
        import pyacoustid as acoustid
        HAS_ACOUSTID = True
    except ImportError:
        HAS_ACOUSTID = False

try:
    from utils.shared_api_client import query_musicbrainz_by_id, query_musicbrainz_fuzzy
except Exception:
    from music_metadata_enhancer.standalone_compat import query_musicbrainz_by_id, query_musicbrainz_fuzzy

logger = logging.getLogger(__name__)


def _generate_acoustid_fingerprint(file_path: Path) -> Optional[tuple[int, str]]:
    """
    Generate AcoustID fingerprint for audio file.
    
    AcoustID requires fpcalc (fingerprint calculator).
    Returns (duration_seconds, fingerprint) or None if failed.
    """
    if not HAS_ACOUSTID:
        logger.debug("acoustid-py not installed, skipping fingerprinting")
        return None

    # pyacoustid relies on Chromaprint's fpcalc binary.
    if shutil.which("fpcalc") is None:
        logger.info("   ⚠️  Picard AcoustID disabled: 'fpcalc' not found in PATH")
        return None
    
    try:
        logger.debug(f"Generating AcoustID fingerprint for {file_path.name}...")
        
        # Calculate fingerprint using acoustid library
        # This internally uses fpcalc if available
        duration, fingerprint = acoustid.fingerprint_file(str(file_path))
        
        if fingerprint:
            logger.debug(f"✅ Fingerprint generated ({len(fingerprint)} chars), duration: {duration}s")
            return int(duration), fingerprint
        else:
            logger.debug("❌ Failed to generate fingerprint")
            return None
    
    except Exception as e:
        logger.debug(f"AcoustID fingerprinting failed: {e}")
        return None


def _identify_via_acoustid(file_path: Path, acoustid_key: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Identify song using AcoustID fingerprint.
    
    Returns MusicBrainz ID and recording info.
    Note: Requires free AcoustID API key from https://acoustid.org/api
    """
    if not HAS_ACOUSTID:
        return None

    if not acoustid_key:
        logger.debug("AcoustID API key missing, skipping fingerprint lookup")
        return None
    
    try:
        fingerprint_data = _generate_acoustid_fingerprint(file_path)
        if not fingerprint_data:
            return None
        duration, fingerprint = fingerprint_data
        
        logger.debug("Querying AcoustID for recording match...")
        
        # Query AcoustID API
        results = acoustid.lookup(acoustid_key, fingerprint, duration, meta='recordings')
        
        # pyacoustid may return either dict or iterable depending on version.
        if isinstance(results, dict):
            result_items = results.get('results') or []
        else:
            # Iterable shape: (score, recording_id, title, artist)
            result_items = []
            for item in results:
                try:
                    score, recording_id, rec_title, rec_artist = item
                    result_items.append({
                        'score': float(score),
                        'recordings': [{'id': recording_id, 'title': rec_title, 'artists': [{'name': rec_artist}] if rec_artist else []}]
                    })
                except Exception:
                    continue

        if result_items:
            best_match = result_items[0]
            
            if 'recordings' in best_match and best_match['recordings']:
                recording = best_match['recordings'][0]
                mbid = recording.get('id')
                score = best_match.get('score', 0)
                
                logger.debug(f"✅ Found match: MBID={mbid}, Score={score:.2f}")
                
                return {
                    'mbid': mbid,
                    'score': score,
                    'title': recording.get('title'),
                    'artists': recording.get('artists', []),
                    'method': 'acoustid'
                }
        
        logger.debug("No AcoustID matches found")
        return None
    
    except Exception as e:
        logger.debug(f"AcoustID lookup failed: {e}")
        return None


def is_enrichment_complete(enriched_metadata: Dict[str, Any]) -> bool:
    """
    Check if enrichment is complete enough to skip fallback.
    
    Fallback triggers if missing:
    - Genre
    - Release date / ISRC
    """
    has_genre = bool(enriched_metadata.get('genre'))
    has_date = bool(enriched_metadata.get('date'))
    has_language = bool(enriched_metadata.get('language'))
    
    # Consider complete if has genre AND (date OR language)
    is_complete = (has_genre and (has_date or has_language))
    
    logger.debug(f"Enrichment completeness: genre={has_genre}, date={has_date}, language={has_language} → complete={is_complete}")
    
    return is_complete


def run_picard_fallback_enrichment(
    file_path: Path,
    existing_metadata: Dict[str, Any],
    acoustid_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Run Picard fallback enrichment to fill missing metadata.
    
    Only triggered if primary enrichment is incomplete.
    
    Returns:
        {
            'ran': bool,
            'metadata_enriched': bool,
            'filled_fields': list,  # Which fields were filled
            'method': str,  # 'acoustid' or 'fuzzy_match'
            'confidence': float,
            'errors': list
        }
    """
    result = {
        'ran': False,
        'metadata_enriched': False,
        'filled_fields': [],
        'method': None,
        'confidence': 0.0,
        'errors': []
    }
    
    try:
        # Check if enrichment is already complete
        if is_enrichment_complete(existing_metadata):
            logger.info("   ℹ️  Primary enrichment complete, skipping Picard fallback")
            return result
        
        logger.info("   🎵 Running Picard fallback enrichment...")
        result['ran'] = True
        
        title = existing_metadata.get('title', '').strip()
        artist = existing_metadata.get('artist', '').strip()
        
        if not (title and artist):
            logger.debug("   ⚠️  Missing title/artist, cannot use Picard fallback")
            result['errors'].append("Missing title/artist")
            return result
        
        if not acoustid_key:
            acoustid_key = (os.getenv("ACOUSTID_API_KEY") or os.getenv("ACOUSTID_KEY") or "").strip()

        # PHASE 1: Try AcoustID fingerprinting
        picard_metadata = None
        if HAS_ACOUSTID and file_path and file_path.exists() and acoustid_key:
            logger.debug("   [PHASE 1] Attempting AcoustID fingerprinting...")
            picard_metadata = _identify_via_acoustid(file_path, acoustid_key)
            
            if picard_metadata:
                # Query full MusicBrainz data using MBID (via shared client)
                if picard_metadata.get('mbid'):
                    full_metadata = query_musicbrainz_by_id(picard_metadata['mbid'])
                    if full_metadata:
                        picard_metadata = full_metadata
                        picard_metadata['confidence'] = picard_metadata.get('confidence', 0.95)
                        result['method'] = 'acoustid'
        else:
            if not HAS_ACOUSTID:
                logger.info("   ⚠️  Picard AcoustID unavailable: pyacoustid/acoustid not installed")
            elif not acoustid_key:
                logger.info("   ⚠️  Picard AcoustID key missing (ACOUSTID_API_KEY)")
            elif not (file_path and file_path.exists()):
                logger.info("   ⚠️  Picard AcoustID skipped: file not found")
        
        # PHASE 2: Fallback to fuzzy MusicBrainz search (via shared client)
        if not picard_metadata:
            logger.debug("   [PHASE 2] Attempting fuzzy MusicBrainz search...")
            picard_metadata = query_musicbrainz_fuzzy(title, artist)

            # Retry with normalized/cleaner query when first fuzzy match fails.
            if not picard_metadata:
                normalized_title = re.sub(r'\s*\([^)]*\)', '', title).strip()
                normalized_title = re.sub(r'\s*\[[^\]]*\]', '', normalized_title).strip()
                normalized_title = re.sub(r'\b(feat|ft|featuring)\b.*$', '', normalized_title, flags=re.IGNORECASE).strip()
                normalized_title = re.sub(r'\s+', ' ', normalized_title).strip()
                if normalized_title and normalized_title != title:
                    logger.debug("   [PHASE 2B] Retrying fuzzy MusicBrainz with normalized title...")
                    picard_metadata = query_musicbrainz_fuzzy(normalized_title, artist)

            if not picard_metadata:
                logger.debug("   [PHASE 2C] Retrying fuzzy MusicBrainz with title-only search...")
                title_only = re.sub(r'\s+', ' ', title).strip()
                if title_only:
                    picard_metadata = query_musicbrainz_fuzzy(title_only, '')

            if picard_metadata:
                result['method'] = 'fuzzy_match'
                picard_metadata['confidence'] = 0.80  # Fuzzy match lower confidence
        
        # Apply Picard results to fill gaps
        if picard_metadata:
            filled_count = 0
            
            # Fill missing genre
            if not existing_metadata.get('genre') and picard_metadata.get('genre'):
                existing_metadata['genre'] = picard_metadata['genre']
                result['filled_fields'].append('genre')
                filled_count += 1
                logger.info(f"      ✅ Filled genre: {picard_metadata['genre']}")
            
            # Fill missing date OR update with Picard's more accurate year
            # Always prefer Picard's release year for accuracy (Picard uses MusicBrainz)
            if picard_metadata.get('release_date'):
                existing_date = existing_metadata.get('date', '').strip()
                picard_year = picard_metadata['release_date'][:4]
                
                if not existing_date:
                    # No date in file, add it
                    existing_metadata['date'] = picard_year
                    result['filled_fields'].append('date')
                    filled_count += 1
                    logger.info(f"      ✅ Filled date: {picard_year}")
                elif existing_date != picard_year:
                    # Date exists but different - prefer Picard (more accurate source)
                    logger.info(f"      ℹ️  Updating date from {existing_date} → {picard_year} (Picard more accurate)")
                    existing_metadata['date'] = picard_year
                    if 'date' not in result['filled_fields']:
                        result['filled_fields'].append('date')
                    filled_count += 1
            
            # Fill missing album
            if not existing_metadata.get('album') and picard_metadata.get('album'):
                existing_metadata['album'] = picard_metadata['album']
                result['filled_fields'].append('album')
                filled_count += 1
                logger.info(f"      ✅ Filled album: {picard_metadata['album']}")
            
            # Override track number with Picard's value (fixes wrong track numbers like 47)
            # Picard gives authoritative track position from MusicBrainz
            if picard_metadata.get('track_number'):
                existing_track = existing_metadata.get('track_number')
                picard_track = str(picard_metadata['track_number'])
                
                if not existing_track:
                    # No track in file, add it
                    existing_metadata['track_number'] = picard_track
                    result['filled_fields'].append('track_number')
                    filled_count += 1
                    logger.info(f"      ✅ Filled track number: {picard_track}")
                elif str(existing_track) != picard_track:
                    # Track exists but different - prefer Picard (authoritative source)
                    logger.info(f"      ℹ️  Correcting track from {existing_track} → {picard_track} (Picard authoritative)")
                    existing_metadata['track_number'] = picard_track
                    if 'track_number' not in result['filled_fields']:
                        result['filled_fields'].append('track_number')
                    filled_count += 1
            
            # Fill ISRC if we have it
            if picard_metadata.get('isrc'):
                existing_metadata['isrc'] = picard_metadata['isrc']
                result['filled_fields'].append('isrc')
                filled_count += 1
            
            if filled_count > 0:
                result['metadata_enriched'] = True
                result['confidence'] = picard_metadata.get('confidence', 0.80)
                logger.info(f"   ✅ Picard fallback enriched {filled_count} fields ({result['method']})")
            else:
                logger.info(f"   ℹ️  No new fields to fill from Picard data")
        
        else:
            logger.info(f"   ⚠️  Picard fallback could not identify song")
    
    except Exception as e:
        logger.error(f"   ❌ Picard fallback error: {e}")
        result['errors'].append(str(e))
    
    return result


def install_requirements():
    """
    Check if required dependencies are installed.
    Provides helpful message if not.
    """
    missing = []
    
    if not HAS_MUSICBRAINZ:
        missing.append("musicbrainzngs")
    if not HAS_ACOUSTID:
        missing.append("acoustid")
    
    if missing:
        logger.warning(f"⚠️  Picard fallback disabled - install with: pip install {' '.join(missing)}")
        return False
    
    return True
