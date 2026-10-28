"""CLI: python -m daw2bms extract song.flp --out output/song"""
from __future__ import annotations

from .i18n import (msg, tr, localized_print as print, split_language_args, language_context,
                   argparse_translations, LANGUAGES, configure_console, resolve_language)

import argparse
import csv
import json
from pathlib import Path
import sys

from . import __version__
from .flp import FlpError, extract_file


def write_csv(path: Path, rows: list[dict], columns: list[str]) -> None:
    # UTF-8 BOM makes channel/pattern names readable in Windows Excel.
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def summary_text(document: dict) -> str:
    p, s = document["project"], document["summary"]
    signature = p["time_signature"]
    lines = [
        tr("DAW2BMS — FLP structure report"), "",
        tr("File: {p0}", p0=document["source"]["file"]),
        tr("Saved FL Studio version: {p0}", p0=p["saved_version"]),
        tr("PPQ: {p0} ticks per quarter note", p0=p["ppq"]),
        tr("Stored BPM: {p0} (not a complete tempo map)", p0=p["stored_tempo_bpm"]),
        tr("Project time signature: {p0}/{p1}", p0=signature["numerator"], p1=signature["denominator"]),
        tr("{p0} channels, {p1} patterns, {p2} pattern notes, {p3} clips, {p4} timeline notes",
           p0=s["channels"], p1=s["patterns"], p2=s["pattern_notes"], p3=s["playlist_clips"], p4=s["timeline_notes"]),
        "", tr("Pattern note counts (before Playlist repetitions):"),
    ]
    for pattern in document["patterns"]:
        lines.append(f"  {pattern['id']:>3}  {pattern['name'] or tr('(unnamed)')}: {len(pattern['notes'])}")
    for arrangement in document["arrangements"]:
        end = max((c["end_ticks"] for c in arrangement["clips"]), default=0)
        active = len({c["track_id"] for c in arrangement["clips"]})
        lines += ["", f"Arrangement {arrangement['id']}: {arrangement['name'] or tr('(unnamed)')}",
                  tr("{p0} tracks with clips; end {p1} ticks / {p2:g} quarter-note beats", p0=active, p1=end, p2=end / p['ppq']),
                  tr("Clip / Track / Pattern / Start tick / Length / Source start / Expansion")]
        for clip in sorted(arrangement["clips"], key=lambda c: (c["position_ticks"], c["track_id"], c["index"])):
            lines.append(f"  {clip['index']:>8}  {clip['track_id']:>4}  {str(clip['pattern_id']):>7}  "
                         f"{clip['position_ticks']:>10}  {clip['length_ticks']:>10}  "
                         f"{str(clip['source_start_ticks']):>12}  {clip['expansion_status']}")
    lines += ["", tr("Conventions and limitations:"),
        tr("Ticks and beats start at zero; beat = tick / PPQ. Track numbers start at one."),
        tr("FL pitch naming: key 60 is C5, not scientific-pitch C4."),
        tr("Zero-length step triggers remain zero; no audio duration is inferred."),
        tr("visible_* records clip intersections; original note durations remain unchanged."),
        tr("Mute state does not remove notes; clip_muted=null means unknown, not unmuted."),
        tr("Looping, automation, swing, transposition and plugin/audio playback are not simulated."),
        "", tr("Diagnostics:")]
    from .i18n import render
    lines.extend(f"  [{w['code']}] {render(w['message'])}" for w in document["warnings"])
    lines += ["", tr("Input SHA-256: {p0}", p0=document['source']['sha256'])]
    return "\n".join(lines) + "\n"


def export(document: dict, destination: Path, force: bool = False) -> None:
    names = ("project.json", "pattern_notes.csv", "playlist.csv", "timeline_notes.csv", "summary.txt")
    source_path = document.get("_source_path")
    if source_path and any((destination / name).resolve() == source_path for name in names):
        raise FlpError(msg('An output file would overwrite the input project'))
    existing = [name for name in names if (destination / name).exists()]
    if existing and not force:
        raise FlpError(msg('Output already exists: {p0}. Use --force to replace generated files.', p0=', '.join(existing)))
    # Serialise before writing any output, so NaN / invalid JSON cannot leave
    # apparently successful but incomplete machine-readable results.
    public = {key: value for key, value in document.items() if not key.startswith("_")}
    content = json.dumps(public, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "project.json").write_text(content, encoding="utf-8")
    ppq = document["project"]["ppq"]
    channels = {c["id"]: c for c in document["channels"]}
    pattern_rows = []
    for pattern in document["patterns"]:
        for note in pattern["notes"]:
            pattern_rows.append({**note, "pattern_id": pattern["id"], "pattern_name": pattern["name"],
                "channel_name": channels[note["channel_id"]]["name"],
                "position_beats": note["position_ticks"] / ppq, "length_beats": note["length_ticks"] / ppq})
    write_csv(destination / "pattern_notes.csv", pattern_rows, [
        "pattern_id", "pattern_name", "index", "channel_id", "channel_name", "position_ticks", "length_ticks",
        "position_beats", "length_beats", "key", "key_name_fl", "velocity_raw", "pan_raw", "release_raw",
        "fine_pitch_raw", "midi_channel_raw", "mod_x_raw", "mod_y_raw", "flags_raw", "slide", "zero_length_trigger",
        "source_byte_offset",
    ])
    clip_rows = [{**clip, "arrangement_id": a["id"], "arrangement_name": a["name"]}
                 for a in document["arrangements"] for clip in a["clips"]]
    write_csv(destination / "playlist.csv", clip_rows, [
        "arrangement_id", "arrangement_name", "index", "native_id", "track_id", "kind", "pattern_id", "channel_id",
        "position_ticks", "length_ticks", "end_ticks", "position_beats", "length_beats", "source_start_ticks",
        "source_end_ticks", "offset_start_bits", "offset_end_bits", "scale_raw", "flags_raw", "muted", "expansion_status",
        "source_byte_offset",
    ])
    timeline = [n for a in document["arrangements"] for n in a["timeline_notes"]]
    write_csv(destination / "timeline_notes.csv", timeline, [
        "arrangement_id", "track_id", "clip_index", "pattern_id", "note_index", "channel_id", "channel_name",
        "key", "key_name_fl", "velocity_raw", "slide", "zero_length_trigger", "pattern_position_ticks",
        "absolute_onset_ticks", "length_ticks", "absolute_end_ticks", "absolute_onset_beats", "length_beats",
        "visible_start_ticks", "visible_end_ticks", "onset_inside_clip", "overlaps_left_edge", "overlaps_right_edge",
        "track_enabled", "channel_enabled", "clip_muted",
    ])
    (destination / "summary.txt").write_text(summary_text(document), encoding="utf-8")


def _parse_args(argv):
    parser = argparse.ArgumentParser(description=tr('FL Studio structure extraction and isolated keysound preparation'))
    parser.add_argument("--version", action="version", version=__version__, help=tr("Show program version and exit"))
    sub = parser.add_subparsers(dest="command", required=True)
    gui_cmd = sub.add_parser("gui", help=tr('Open the PyQt6 desktop interface'))
    gui_cmd.add_argument("source", nargs="?", type=Path, help=tr('Optional project to prefill'))
    convert_cmd = sub.add_parser("convert", help=tr('FLP -> adaptive keysounds -> BMS in one command'))
    convert_cmd.add_argument("source", type=Path)
    convert_cmd.add_argument("--out", type=Path, help=tr('New output directory; default output/<project>-bms (auto-numbered if needed)'))
    convert_cmd.add_argument("--fl-exe", type=Path, help=tr('Override automatic FL Studio discovery'))
    convert_cmd.add_argument("--initial-tail", type=float, default=1.0)
    convert_cmd.add_argument("--max-tail", type=float, default=30.0)
    convert_cmd.add_argument("--max-attempts", type=int, default=5)
    convert_cmd.add_argument("--threshold-db", type=float, default=-60)
    convert_cmd.add_argument("--timeout", type=float, default=600)
    convert_cmd.add_argument("--channels")
    convert_cmd.add_argument("--midi-only")
    convert_cmd.add_argument("--resource-dir", type=Path, action="append", default=[])
    convert_cmd.add_argument("--no-dedupe", action="store_true")
    convert_cmd.add_argument("--arrangement", type=int)
    convert_cmd.add_argument("--title")
    convert_cmd.add_argument("--artist")
    convert_cmd.add_argument("--lead-in-bars", type=int, default=1)
    convert_cmd.add_argument("--play-channels")
    convert_cmd.add_argument("--encoding", choices=("utf-8", "cp932"), default="utf-8")
    extract = sub.add_parser("extract", help=tr('Extract FLP notes and playlist geometry to JSON/CSV'))
    extract.add_argument("source", type=Path)
    extract.add_argument("--out", type=Path, help=tr('Output directory (default: output/<source stem>)'))
    extract.add_argument("--force", action="store_true", help=tr('Replace generated output files'))
    prepare_cmd = sub.add_parser("prepare", help=tr('Create an isolated-note FLP copy and a cutting manifest'))
    prepare_cmd.add_argument("source", type=Path)
    prepare_cmd.add_argument("--out", type=Path, required=True, help=tr('New bank directory (must not exist)'))
    prepare_cmd.add_argument("--tail", type=float, default=3.0, help=tr('Release capture seconds after each note (default 3)'))
    prepare_cmd.add_argument("--gap", type=float, default=0.5, help=tr('Additional quiet guard seconds (default 0.5)'))
    prepare_cmd.add_argument("--channels", help=tr('Comma-separated Channel Rack IDs; omit for all placed notes'))
    prepare_cmd.add_argument("--arrangement", type=int, help=tr('Arrangement ID (default first)'))
    prepare_cmd.add_argument("--no-dedupe", action="store_true", help=tr('Render every placement separately'))
    prepare_cmd.add_argument("--fl-exe", type=Path, help=tr('FL executable, for resource preflight (otherwise detect installations)'))
    prepare_cmd.add_argument("--resource-dir", type=Path, action="append", default=[], help=tr('Additional sample/FLEX pack directory; repeatable'))
    prepare_cmd.add_argument("--midi-only", help=tr('Comma-separated IDs forced to MIDI-only fallback'))
    render_cmd = sub.add_parser("render", help=tr("Render a prepared bank with FL's CLI (no UI automation)"))
    render_cmd.add_argument("manifest", type=Path)
    render_cmd.add_argument("--fl-exe", type=Path, required=True)
    render_cmd.add_argument("--timeout", type=float, default=600)
    slice_cmd = sub.add_parser("slice", help=tr('Validate and split a bank WAV into independent keysounds'))
    slice_cmd.add_argument("manifest", type=Path)
    slice_cmd.add_argument("--wav", type=Path, help=tr("Manual export WAV (default manifest's bank WAV)"))
    slice_cmd.add_argument("--out", type=Path, help=tr('New keysound directory (default <bank>/keysounds)'))
    slice_cmd.add_argument("--threshold-db", type=float, default=-60)
    slice_cmd.add_argument("--tail-pad-ms", type=float, default=20)
    slice_cmd.add_argument("--fade-ms", type=float, default=3)
    slice_cmd.add_argument("--subtype", choices=("PCM_16", "PCM_24", "FLOAT"), default="PCM_24")
    slice_cmd.add_argument("--offset-ms", type=float, default=0, help=tr('Explicit render alignment correction'))
    cut_cmd = sub.add_parser("cut", help=tr('Adaptive render/cut: measure release tails and retry only failing keys'))
    cut_cmd.add_argument("source", type=Path)
    cut_cmd.add_argument("--out", type=Path, required=True)
    cut_cmd.add_argument("--fl-exe", type=Path, required=True)
    cut_cmd.add_argument("--initial-tail", type=float, default=1.0, help=tr('Initial probe coverage, not final WAV duration'))
    cut_cmd.add_argument("--max-tail", type=float, default=30.0, help=tr('Per-key retry ceiling; reaching it reports failure'))
    cut_cmd.add_argument("--max-attempts", type=int, default=5)
    cut_cmd.add_argument("--threshold-db", type=float, default=-60)
    cut_cmd.add_argument("--timeout", type=float, default=600)
    cut_cmd.add_argument("--channels")
    cut_cmd.add_argument("--midi-only")
    cut_cmd.add_argument("--resource-dir", type=Path, action="append", default=[])
    cut_cmd.add_argument("--no-dedupe", action="store_true")
    cut_cmd.add_argument("--resume", type=Path, help=tr('Reuse a completed, non-looping render bank manifest for the first measurement'))
    bms_cmd = sub.add_parser("bms", help=tr('Export a validated keysound package as a playable 7-key BME test chart'))
    bms_cmd.add_argument("keysounds", type=Path)
    bms_cmd.add_argument("--out", type=Path, required=True)
    bms_cmd.add_argument("--title")
    bms_cmd.add_argument("--artist", default="Unknown")
    bms_cmd.add_argument("--lead-in-bars", type=int, default=1)
    bms_cmd.add_argument("--play-channels", help=tr('Comma-separated FL channel IDs to play; others become BGM'))
    bms_cmd.add_argument("--encoding", choices=("utf-8", "cp932"), default="utf-8")
    for target in (parser, *sub.choices.values()):
        target.add_argument("--lang", choices=list(LANGUAGES), help=tr("Display language: zh-TW, en, ja or ko"))
    return parser.parse_args(argv)


def _run(args):
    try:
        if args.command == "gui":
            from .gui import main as gui_main
            return gui_main((["--lang", args.explicit_language] if args.explicit_language else []) + ([str(args.source)] if args.source else []))
        if args.command == "convert":
            from .pipeline import convert
            try:
                selected = [{int(v) for v in raw.split(",")} if raw else None
                            for raw in (args.channels, args.midi_only, args.play_channels)]
            except ValueError as exc:
                raise FlpError(msg('Channel selections must be comma-separated integer IDs')) from exc
            report = convert(args.source, args.out, fl_exe=args.fl_exe,
                             initial_tail=args.initial_tail, max_tail=args.max_tail, max_attempts=args.max_attempts,
                             threshold_db=args.threshold_db, timeout=args.timeout,
                             channels=selected[0], midi_only=selected[1], play_channels=selected[2],
                             resource_dirs=tuple(args.resource_dir), deduplicate=not args.no_dedupe,
                             arrangement_id=args.arrangement, title=args.title, artist=args.artist,
                             lead_in_bars=args.lead_in_bars, encoding=args.encoding,
                             progress=lambda message: print(message, file=sys.stderr if message.startswith("WARNING:") else sys.stdout, flush=True))
            output = Path(report["output_directory"])
            print(msg('Result: {p0}', p0=report['status']))
            if report["chart"]:
                print(msg('Chart: {p0}', p0=output / report['chart']))
            if report["midi"]:
                print(msg('MIDI: {p0}', p0=output / report['midi']))
            print(msg('Report: {p0}', p0=output / 'conversion.json'))
            return 0
        if args.command == "bms":
            from .bms import export_bms
            try:
                selected = {int(v) for v in args.play_channels.split(",")} if args.play_channels else None
            except ValueError as exc:
                raise FlpError(msg('--play-channels must be comma-separated integer IDs')) from exc
            report = export_bms(args.keysounds, args.out, title=args.title, artist=args.artist,
                                lead_in_bars=args.lead_in_bars, play_channels=selected, encoding=args.encoding)
            for warning in report["warnings"]:
                print(msg('WARNING: {p0}', p0=warning), file=sys.stderr)
            print(msg('Exported {p0} playable notes + {p1} BGM events; {p2} notes kept as MIDI only.', p0=report['playable_notes'], p1=report['bgm_events'], p2=report['midi_only_notes']))
            print(msg('Chart: {p0}', p0=(args.out / report['chart']).resolve()))
            return 0
        if args.command == "cut":
            from .adaptive import cut
            try:
                channels = {int(v) for v in args.channels.split(",")} if args.channels else None
                midi_only = {int(v) for v in args.midi_only.split(",")} if args.midi_only else None
            except ValueError as exc:
                raise FlpError(msg('Channel selections must be comma-separated integer IDs')) from exc
            cut(args.source, args.out, args.fl_exe, initial_tail=args.initial_tail, max_tail=args.max_tail,
                max_attempts=args.max_attempts, threshold_db=args.threshold_db, timeout=args.timeout,
                resume=args.resume, channels=channels, midi_only=midi_only, resource_dirs=tuple(args.resource_dir),
                deduplicate=not args.no_dedupe, progress=lambda message: print(message, file=sys.stderr if message.startswith("WARNING:") else sys.stdout, flush=True))
            print(msg('Output: {p0}', p0=args.out.resolve()))
            return 0
        if args.command == "prepare":
            from .keysounds import prepare
            try:
                selected = {int(v) for v in args.channels.split(",")} if args.channels is not None else None
                midi_only = {int(v) for v in args.midi_only.split(",")} if args.midi_only is not None else None
            except ValueError as exc:
                raise FlpError(msg('--channels and --midi-only must be comma-separated integer IDs')) from exc
            result = prepare(args.source, args.out, tail_seconds=args.tail, gap_seconds=args.gap,
                             channels=selected, arrangement_id=args.arrangement, deduplicate=not args.no_dedupe,
                             fl_exe=args.fl_exe, resource_dirs=tuple(args.resource_dir), midi_only=midi_only)
            from .resources import resource_warnings
            for warning in resource_warnings(result["resources"]):
                print(warning, file=sys.stderr)
            for warning in result["midi_warnings"]:
                print(msg('WARNING: MIDI export: {p0}', p0=warning), file=sys.stderr)
            print(msg('Prepared {p0} keys for {p1} placed notes.', p0=len(result['keys']), p1=len(result['timeline'])))
            print(msg('MIDI-only fallback: {p0} notes; full selection: song.mid', p0=len(result['fallback']['notes'])))
            print(msg('Manifest: {p0}', p0=(args.out / 'manifest.json').resolve()))
            return 0
        if args.command == "render":
            from .audio import render
            print(msg('Rendering with FL Studio command line; no UI automation.'), flush=True)
            result = render(args.manifest, args.fl_exe, timeout=args.timeout)
            if result["status"] == "midi_only":
                print(msg('WARNING: All selected notes are MIDI-only; rendering skipped. See fallback.mid.'), file=sys.stderr)
                return 0
            print(msg('Rendered {p0} frames at {p1} Hz in {p2:.1f}s.', p0=result['frames'], p1=result['samplerate'], p2=result['elapsed_seconds']))
            return 0
        if args.command == "slice":
            from .audio import slice_bank
            result = slice_bank(args.manifest, wav_path=args.wav, destination=args.out,
                                threshold_db=args.threshold_db, tail_pad_ms=args.tail_pad_ms,
                                fade_ms=args.fade_ms, subtype=args.subtype, offset_ms=args.offset_ms)
            if result["status"] == "midi_only":
                print(msg('WARNING: All selected notes are MIDI-only; audio cutting skipped. See fallback.mid.'), file=sys.stderr)
                return 0
            print(msg('Created {p0} keysounds; all audio checks passed.', p0=len(result['keys'])))
            print(msg('Output: {p0}', p0=(args.out or args.manifest.resolve().parent / 'keysounds').resolve()))
            return 0
        document = extract_file(args.source)
        document["_source_path"] = args.source.resolve()
        destination = args.out or Path("output") / args.source.stem
        export(document, destination, args.force)
    except (OSError, FlpError) as exc:
        print(msg('Error: {p0}', p0=exc), file=sys.stderr)
        return 1
    summary = document["summary"]
    print(msg('FL {p0} | PPQ {p1}', p0=document['project']['saved_version'], p1=document['project']['ppq']))
    print(msg('{p0} channels, {p1} patterns, {p2} pattern notes, {p3} clips, {p4} timeline notes', p0=summary['channels'], p1=summary['patterns'], p2=summary['pattern_notes'], p3=summary['playlist_clips'], p4=summary['timeline_notes']))
    skipped = sum(c["expansion_status"] == "unsupported" for a in document["arrangements"] for c in a["clips"])
    print(msg('Structural extraction only; {p0} unsupported clips. See summary.txt for limitations.', p0=skipped))
    print(msg('Output: {p0}', p0=destination.resolve()))
    return 0


def main(argv: list[str] | None = None) -> int:
    configure_console()
    try:
        language, cleaned, explicit = split_language_args(list(sys.argv[1:] if argv is None else argv))
    except ValueError as exc:
        with language_context(resolve_language()):
            print(msg("Error: {p0}", p0=exc), file=sys.stderr)
        return 2
    with language_context(language):
        with argparse_translations():
            args = _parse_args(cleaned)
        args.explicit_language = explicit
        return _run(args)


if __name__ == "__main__":
    raise SystemExit(main())
