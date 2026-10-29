"""Source-track inventory shared by the CLI and the desktop track-role editor."""
from collections import Counter
from pathlib import Path

from .flp import FlpError
from .i18n import msg
from .keysounds import sha256_file


def inspect_tracks(source):
    source = Path(source).expanduser().resolve()
    if source.suffix.lower() == ".als":
        from .als import extract_file
        document = extract_file(source)
        arrangements = [{"id": 0, "name": "Arrangement", "tracks": document["tracks"],
                         "clips": [c for c in document["clips"] if c["scope"] == "arrangement"],
                         "timeline_notes": [n for n in document["timeline_notes"] if n["midi_eligible"]]}]
    else:
        from .flp import extract_file
        document = extract_file(source)
        arrangements = document["arrangements"]
    if sha256_file(source) != document["source"]["sha256"]:
        raise FlpError(msg("Input project changed during conversion; no chart will be published"))
    result = []
    for arrangement in arrangements:
        counts = Counter(n["track_id"] for n in arrangement["timeline_notes"])
        clips = arrangement["clips"]
        used = {c["track_id"] for c in clips} | set(counts)
        tracks = []
        for track in arrangement["tracks"]:
            ident = track["id"]
            if ident not in used:
                continue
            own = [c for c in clips if c["track_id"] == ident]
            content_names = list(dict.fromkeys(n.get('channel_name', '') for n in arrangement['timeline_notes']
                                               if n['track_id'] == ident and n.get('channel_name')))
            supported = (bool(counts[ident]) and track.get("enabled", True)
                         and all(c["kind"] in ("pattern", "midi") for c in own))
            if source.suffix.lower() != '.als':
                supported = supported and all(c['expansion_status'] == 'single_pass' for c in own)
                supported = supported and all(n.get('channel_enabled', True) for n in arrangement['timeline_notes'] if n['track_id'] == ident)
            tracks.append({"id": ident, "name": track.get("name") or ' / '.join(content_names), "notes": counts[ident],
                           "source_track_name": track.get('name'), "content_names": content_names,
                           "clips": len(own), "supported": bool(supported)})
        result.append({"id": arrangement["id"], "name": arrangement.get("name") or "", "tracks": tracks})
    return {"path": str(source), "sha256": document["source"]["sha256"],
            "daw": "ableton_live" if source.suffix.lower() == ".als" else "fl_studio", "arrangements": result}


def track_policy(known, play_tracks=None, exclude_tracks=None):
    known, excluded = set(known), set(exclude_tracks or ())
    if not excluded <= known or (play_tracks is not None and not set(play_tracks) <= known):
        raise FlpError(msg("Track selections must refer to IDs in the selected Arrangement."))
    if play_tracks is not None and set(play_tracks) & excluded:
        raise FlpError(msg("A track cannot be both playable and excluded."))
    return {str(i): "exclude" if i in excluded else "play" if play_tracks is None or i in play_tracks else "bgm" for i in sorted(known)}


def parse_track_ids(raw):
    if raw is None:
        return None
    if raw.strip().lower() == "none":
        return set()
    try:
        values = {int(v.strip()) for v in raw.split(",")}
        if not values or any(i < 0 for i in values): raise ValueError()
        return values
    except ValueError as exc:
        raise FlpError(msg("Track selections must be comma-separated IDs, or 'none'.")) from exc
