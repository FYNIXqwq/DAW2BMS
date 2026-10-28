"""CLI: python -m daw2bms extract song.flp --out output/song"""
from __future__ import annotations

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
        "DAW2BMS — FLP 结构提取报告", "",
        f"文件：{document['source']['file']}",
        f"文件保存版本：FL Studio {p['saved_version']}",
        f"PPQ：{p['ppq']} ticks / 四分音符",
        f"文件中保存的 BPM：{p['stored_tempo_bpm']}（不是完整变速曲线）",
        f"项目拍号字段：{signature['numerator']}/{signature['denominator']}",
        f"Channel Rack：{s['channels']} 个通道；Pattern：{s['patterns']} 个；原始音符：{s['pattern_notes']}",
        f"Arrangement：{s['arrangements']} 个；Playlist 片段：{s['playlist_clips']} 个；展开记录：{s['timeline_notes']}",
        "", "Pattern 音符数（不含 Playlist 重复放置）：",
    ]
    for pattern in document["patterns"]:
        lines.append(f"  {pattern['id']:>3}  {pattern['name'] or '(未命名)'}：{len(pattern['notes'])}")
    for arrangement in document["arrangements"]:
        end = max((c["end_ticks"] for c in arrangement["clips"]), default=0)
        active = len({c["track_id"] for c in arrangement["clips"]})
        lines += ["", f"Arrangement {arrangement['id']}：{arrangement['name'] or '(未命名)'}",
                  f"  {active} 条有片段的轨道；结束位置 {end} ticks / {end / p['ppq']:g} beats",
                  "  片段编号  轨道  Pattern  起点(tick)  长度(tick)  源起点(tick)  展开状态"]
        for clip in sorted(arrangement["clips"], key=lambda c: (c["position_ticks"], c["track_id"], c["index"])):
            lines.append(f"  {clip['index']:>8}  {clip['track_id']:>4}  {str(clip['pattern_id']):>7}  "
                         f"{clip['position_ticks']:>10}  {clip['length_ticks']:>10}  "
                         f"{str(clip['source_start_ticks']):>12}  {clip['expansion_status']}")
    lines += ["", "字段约定与边界：",
        "  tick 和 beat 均从 0 开始；beat = tick / PPQ（四分音符），轨道编号从 1 开始。",
        "  key_name_fl 使用 FL 命名：key 60 = C5；不是科学音高命名中的 C4。",
        "  length_ticks=0 是步进触发音符，保留为 0，不猜测音频时长。",
        "  timeline 是单次 Pattern 放置后的几何交集；visible_* 为片段内可见范围，原始音符时值不变。",
        "  静音状态不用于删音；clip_muted=null 表示未解码，不代表未静音。",
        "  不计算循环重复、自动化、摆动、移调、音频或插件播放；不输出推断秒数。",
        "  本报告不能替代 FL Studio 实际播放结果；不支持的片段仍保留原始结构。", "", "诊断："]
    lines.extend(f"  [{w['code']}] {w['message']}" for w in document["warnings"])
    lines += ["", f"输入 SHA-256：{document['source']['sha256']}"]
    return "\n".join(lines) + "\n"


def export(document: dict, destination: Path, force: bool = False) -> None:
    names = ("project.json", "pattern_notes.csv", "playlist.csv", "timeline_notes.csv", "summary.txt")
    source_path = document.get("_source_path")
    if source_path and any((destination / name).resolve() == source_path for name in names):
        raise FlpError("An output file would overwrite the input project")
    existing = [name for name in names if (destination / name).exists()]
    if existing and not force:
        raise FlpError(f"Output already exists: {', '.join(existing)}. Use --force to replace generated files.")
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FL Studio structure extraction and isolated keysound preparation")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    extract = sub.add_parser("extract", help="Extract FLP notes and playlist geometry to JSON/CSV")
    extract.add_argument("source", type=Path)
    extract.add_argument("--out", type=Path, help="Output directory (default: output/<source stem>)")
    extract.add_argument("--force", action="store_true", help="Replace generated output files")
    prepare_cmd = sub.add_parser("prepare", help="Create an isolated-note FLP copy and a cutting manifest")
    prepare_cmd.add_argument("source", type=Path)
    prepare_cmd.add_argument("--out", type=Path, required=True, help="New bank directory (must not exist)")
    prepare_cmd.add_argument("--tail", type=float, default=3.0, help="Release capture seconds after each note (default 3)")
    prepare_cmd.add_argument("--gap", type=float, default=0.5, help="Additional quiet guard seconds (default 0.5)")
    prepare_cmd.add_argument("--channels", help="Comma-separated Channel Rack IDs; omit for all placed notes")
    prepare_cmd.add_argument("--arrangement", type=int, help="Arrangement ID (default first)")
    prepare_cmd.add_argument("--no-dedupe", action="store_true", help="Render every placement separately")
    prepare_cmd.add_argument("--fl-exe", type=Path, help="FL executable, for resource preflight (otherwise detect installations)")
    prepare_cmd.add_argument("--resource-dir", type=Path, action="append", default=[], help="Additional sample/FLEX pack directory; repeatable")
    prepare_cmd.add_argument("--midi-only", help="Comma-separated IDs forced to MIDI-only fallback")
    render_cmd = sub.add_parser("render", help="Render a prepared bank with FL's CLI (no UI automation)")
    render_cmd.add_argument("manifest", type=Path)
    render_cmd.add_argument("--fl-exe", type=Path, required=True)
    render_cmd.add_argument("--timeout", type=float, default=600)
    slice_cmd = sub.add_parser("slice", help="Validate and split a bank WAV into independent keysounds")
    slice_cmd.add_argument("manifest", type=Path)
    slice_cmd.add_argument("--wav", type=Path, help="Manual export WAV (default manifest's bank WAV)")
    slice_cmd.add_argument("--out", type=Path, help="New keysound directory (default <bank>/keysounds)")
    slice_cmd.add_argument("--threshold-db", type=float, default=-60)
    slice_cmd.add_argument("--tail-pad-ms", type=float, default=20)
    slice_cmd.add_argument("--fade-ms", type=float, default=3)
    slice_cmd.add_argument("--subtype", choices=("PCM_16", "PCM_24", "FLOAT"), default="PCM_24")
    slice_cmd.add_argument("--offset-ms", type=float, default=0, help="Explicit render alignment correction")
    cut_cmd = sub.add_parser("cut", help="Adaptive render/cut: measure release tails and retry only failing keys")
    cut_cmd.add_argument("source", type=Path)
    cut_cmd.add_argument("--out", type=Path, required=True)
    cut_cmd.add_argument("--fl-exe", type=Path, required=True)
    cut_cmd.add_argument("--initial-tail", type=float, default=1.0, help="Initial probe coverage, not final WAV duration")
    cut_cmd.add_argument("--max-tail", type=float, default=30.0, help="Per-key retry ceiling; reaching it reports failure")
    cut_cmd.add_argument("--max-attempts", type=int, default=5)
    cut_cmd.add_argument("--threshold-db", type=float, default=-60)
    cut_cmd.add_argument("--timeout", type=float, default=600)
    cut_cmd.add_argument("--channels")
    cut_cmd.add_argument("--midi-only")
    cut_cmd.add_argument("--resource-dir", type=Path, action="append", default=[])
    cut_cmd.add_argument("--no-dedupe", action="store_true")
    cut_cmd.add_argument("--resume", type=Path, help="Reuse a completed, non-looping render bank manifest for the first measurement")
    bms_cmd = sub.add_parser("bms", help="Export a validated keysound package as a playable 7-key BME test chart")
    bms_cmd.add_argument("keysounds", type=Path)
    bms_cmd.add_argument("--out", type=Path, required=True)
    bms_cmd.add_argument("--title")
    bms_cmd.add_argument("--artist", default="Unknown")
    bms_cmd.add_argument("--lead-in-bars", type=int, default=1)
    bms_cmd.add_argument("--play-channels", help="Comma-separated FL channel IDs to play; others become BGM")
    bms_cmd.add_argument("--encoding", choices=("utf-8", "cp932"), default="utf-8")
    args = parser.parse_args(argv)
    try:
        if args.command == "bms":
            from .bms import export_bms
            try:
                selected = {int(v) for v in args.play_channels.split(",")} if args.play_channels else None
            except ValueError as exc:
                raise FlpError("--play-channels must be comma-separated integer IDs") from exc
            report = export_bms(args.keysounds, args.out, title=args.title, artist=args.artist,
                                lead_in_bars=args.lead_in_bars, play_channels=selected, encoding=args.encoding)
            for warning in report["warnings"]:
                print(f"WARNING: {warning}", file=sys.stderr)
            print(f"Exported {report['playable_notes']} playable notes + {report['bgm_events']} BGM events; "
                  f"{report['midi_only_notes']} notes kept as MIDI only.")
            print(f"Chart: {(args.out / report['chart']).resolve()}")
            return 0
        if args.command == "cut":
            from .adaptive import cut
            try:
                channels = {int(v) for v in args.channels.split(",")} if args.channels else None
                midi_only = {int(v) for v in args.midi_only.split(",")} if args.midi_only else None
            except ValueError as exc:
                raise FlpError("Channel selections must be comma-separated integer IDs") from exc
            cut(args.source, args.out, args.fl_exe, initial_tail=args.initial_tail, max_tail=args.max_tail,
                max_attempts=args.max_attempts, threshold_db=args.threshold_db, timeout=args.timeout,
                resume=args.resume, channels=channels, midi_only=midi_only, resource_dirs=tuple(args.resource_dir),
                deduplicate=not args.no_dedupe, progress=lambda message: print(message, flush=True))
            print(f"Output: {args.out.resolve()}")
            return 0
        if args.command == "prepare":
            from .keysounds import prepare
            try:
                selected = {int(v) for v in args.channels.split(",")} if args.channels is not None else None
                midi_only = {int(v) for v in args.midi_only.split(",")} if args.midi_only is not None else None
            except ValueError as exc:
                raise FlpError("--channels and --midi-only must be comma-separated integer IDs") from exc
            result = prepare(args.source, args.out, tail_seconds=args.tail, gap_seconds=args.gap,
                             channels=selected, arrangement_id=args.arrangement, deduplicate=not args.no_dedupe,
                             fl_exe=args.fl_exe, resource_dirs=tuple(args.resource_dir), midi_only=midi_only)
            from .resources import resource_warnings
            for warning in resource_warnings(result["resources"]):
                print(warning, file=sys.stderr)
            for warning in result["midi_warnings"]:
                print(f"WARNING: MIDI export: {warning}", file=sys.stderr)
            print(f"Prepared {len(result['keys'])} keys for {len(result['timeline'])} placed notes.")
            print(f"MIDI-only fallback: {len(result['fallback']['notes'])} notes; full selection: song.mid")
            print(f"Manifest: {(args.out / 'manifest.json').resolve()}")
            return 0
        if args.command == "render":
            from .audio import render
            print("Rendering with FL Studio command line; no UI automation.", flush=True)
            result = render(args.manifest, args.fl_exe, timeout=args.timeout)
            if result["status"] == "midi_only":
                print("WARNING: All selected notes are MIDI-only; rendering skipped. See fallback.mid.", file=sys.stderr)
                return 0
            print(f"Rendered {result['frames']} frames at {result['samplerate']} Hz in {result['elapsed_seconds']:.1f}s.")
            return 0
        if args.command == "slice":
            from .audio import slice_bank
            result = slice_bank(args.manifest, wav_path=args.wav, destination=args.out,
                                threshold_db=args.threshold_db, tail_pad_ms=args.tail_pad_ms,
                                fade_ms=args.fade_ms, subtype=args.subtype, offset_ms=args.offset_ms)
            if result["status"] == "midi_only":
                print("WARNING: All selected notes are MIDI-only; audio cutting skipped. See fallback.mid.", file=sys.stderr)
                return 0
            print(f"Created {len(result['keys'])} keysounds; all audio checks passed.")
            print(f"Output: {(args.out or args.manifest.resolve().parent / 'keysounds').resolve()}")
            return 0
        document = extract_file(args.source)
        document["_source_path"] = args.source.resolve()
        destination = args.out or Path("output") / args.source.stem
        export(document, destination, args.force)
    except (OSError, FlpError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    summary = document["summary"]
    print(f"FL {document['project']['saved_version']} | PPQ {document['project']['ppq']}")
    print(f"{summary['channels']} channels, {summary['patterns']} patterns, "
          f"{summary['pattern_notes']} pattern notes, {summary['playlist_clips']} clips, "
          f"{summary['timeline_notes']} timeline notes")
    skipped = sum(c["expansion_status"] == "unsupported" for a in document["arrangements"] for c in a["clips"])
    print(f"Structural extraction only; {skipped} unsupported clips. See summary.txt for limitations.")
    print(f"Output: {destination.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
