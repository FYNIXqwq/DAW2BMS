"""Filesystem-only preflight for sample files, FLEX packs and VST binaries.

This does not load plugins, inspect windows or verify plugin licenses. Opaque
third-party sample libraries remain unverified and are reported as such.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import struct

from .flp import read_events, text_value


def installed_fl_roots() -> list[Path]:
    roots = []
    for name in ("ProgramFiles", "ProgramFiles(x86)"):
        base = Path(os.environ.get(name, "C:/Program Files")) / "Image-Line"
        if base.is_dir():
            roots.extend(p for p in base.glob("FL Studio *") if (p / "FL64.exe").is_file())
    return sorted(set(roots), key=lambda p: p.name, reverse=True)


def generator_states(source_bytes: bytes) -> dict[int, dict]:
    _, events = read_events(source_bytes)
    states = {}
    channel = None
    scope = None
    for event in events:
        if event.id == 64:
            channel, scope = event.uint, "channel"
            states[channel] = {}
        elif event.id == 65:
            scope = "pattern"
        elif event.id in (99, 98):
            scope = "other"
        if scope == "channel" and event.id in (201, 212, 213):
            states[channel][event.id] = event.data
    return states


def flex_pack_name(state: bytes) -> str | None:
    # Observed FLEX v1 state: version/flags/length header followed by a fixed
    # NUL-terminated pack-name field at offset 16. Reject unfamiliar layouts.
    if len(state) < 17 or state[:8] != struct.pack("<II", 1, 1):
        return None
    field = state[16:272]
    if b"\0" not in field:
        return None
    try:
        name = field.split(b"\0", 1)[0].decode("utf-8")
    except UnicodeError:
        return None
    if not name or not name.isprintable() or any(char in name for char in '/\\:'):
        return None
    return name.removesuffix(".flexpack")


def vst_path(state: bytes) -> str | None:
    if len(state) < 4 or struct.unpack_from("<I", state)[0] not in (6, 8, 9, 10, 11, 12):
        return None
    position = 4
    while position + 12 <= len(state):
        kind, size = struct.unpack_from("<IQ", state, position)
        position += 12
        if size > len(state) - position:
            return None
        if kind == 55:
            try:
                return state[position:position + size].decode("utf-8").rstrip("\0")
            except UnicodeError:
                return None
        position += size
    return None


def mixer_plugin_states(source_bytes: bytes) -> list[dict]:
    """Collect plugins before their closing slot event (98), including slot 0.

    Mixer routing is not yet decoded: callers must not assume an effect only
    touches a single generator. Insert indexes here are serialization order.
    """
    _, events = read_events(source_bytes)
    result, pending = [], None
    after_channels, insert_index = False, 0
    for event in events:
        if event.id == 99:
            after_channels = True
        if not after_channels:
            continue
        if event.id == 201:
            if pending is not None:
                result.append(pending)
            pending = {"plugin": text_value(event), "state": b"", "insert_index": insert_index, "slot_index": None}
        elif event.id == 213 and pending is not None:
            pending["state"] = event.data
        elif event.id == 98 and pending is not None:
            pending["slot_index"] = event.uint
            result.append(pending)
            pending = None
        elif event.id == 147:
            if pending is not None:
                result.append(pending)
                pending = None
            insert_index += 1
    if pending is not None:
        result.append(pending)
    return result


def _plugin_token(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.casefold())


def native_inventory(roots: list[Path], extras: list[Path]) -> dict[str, Path]:
    inventory = {}
    directories = [root / "Plugins/Fruity" for root in roots] + extras
    for root in directories:
        if not root.is_dir():
            continue
        for path in root.rglob("*.dll"):
            stem = path.stem.casefold()
            if stem.endswith("_x86"):
                continue
            inventory[_plugin_token(stem.removesuffix("_x64"))] = path.resolve()
    return inventory


def _plugin_binary_exists(path: Path) -> bool:
    if path.is_file():
        return True
    if path.suffix.casefold() == ".vst3" and path.is_dir():
        binaries = path / "Contents/x86_64-win"
        return binaries.is_dir() and any(p.is_file() for p in binaries.glob("*.vst3"))
    return False


def inspect_plugin(name: str, state: bytes, inventory: dict[str, Path], extras: list[Path]) -> dict:
    """Same policy for generators and effects; unknown identity fails to MIDI."""
    result = {"plugin": name, "missing": [], "blockers": [], "unverified": [], "resolved_vst": None}
    if not name:
        if state:
            result["blockers"].append({"kind": "unknown_plugin", "resource": "Plugin identity is unavailable"})
        return result
    if name.casefold() == "fruity wrapper":
        plugin_file = vst_path(state)
        if plugin_file:
            candidates = [Path(plugin_file)] + [p / Path(plugin_file).name for p in extras]
            found = next((p.resolve() for p in candidates if _plugin_binary_exists(p)), None)
            if found:
                result["resolved_vst"] = str(found)
            else:
                result["missing"].append({"kind": "vst", "resource": plugin_file})
        else:
            result["blockers"].append({"kind": "unresolved_plugin", "resource": "Cannot resolve Fruity Wrapper plugin binary"})
        result["unverified"].append("Plugin-internal libraries and activation are not checked")
    elif _plugin_token(name) not in inventory:
        result["missing"].append({"kind": "native_plugin", "resource": name,
                                  "detail": "No matching native plugin binary in configured installation/resource directories"})
    if name.casefold() == "patcher":
        result["blockers"].append({"kind": "opaque_plugin_container", "resource": "Patcher nested plugin dependencies are not decoded"})
    return result


def resource_warnings(resources: list[dict]):
    """Emit each shared effect dependency once, with an explicit fallback scope."""
    effects = set()
    for resource in resources:
        if resource["status"] != "midi_only":
            continue
        own = resource["missing"] + resource.get("blockers", [])
        if own:
            detail = ", ".join(item["resource"] for item in own)
            yield f"WARNING: Channel {resource['channel_id']} ({resource['channel_name']}): unavailable/unverified {detail}; MIDI only, audio skipped."
        for effect in resource.get("blocking_effects", []):
            identity = (effect["insert_index"], effect["slot_index"], effect["plugin"])
            if identity in effects:
                continue
            effects.add(identity)
            detail = ", ".join(item["resource"] for item in effect["missing"] + effect["blockers"])
            yield (f"WARNING: Mixer effect {effect['plugin']!r} (insert {effect['insert_index']}, slot {effect['slot_index']}): "
                   f"unavailable/unverified {detail}; routing is unresolved, all selected notes kept as MIDI; audio skipped.")


def check_resources(document: dict, source: Path, source_bytes: bytes, *, fl_exe: Path | None = None,
                    resource_dirs: tuple[Path, ...] = (), midi_only: set[int] | None = None) -> list[dict]:
    fl_roots = [fl_exe.resolve().parent] if fl_exe else installed_fl_roots()
    extras = [p.resolve() for p in resource_dirs]
    documents = Path.home() / "Documents"
    user_roots = [documents / "Image-Line", documents / "Image-Line/FL Studio"]
    # Custom User data roots and relocated library directories can be supplied
    # explicitly. Limit scans to those roots; never crawl the whole computer.
    flex_dirs = ([p / "Data/Patches/Packs/FLEX/Packs" for p in fl_roots]
                 + [p / "FLEX/Packs" for p in user_roots]
                 + extras + [p / "FLEX/Packs" for p in extras])
    flex_files = {p.name.casefold(): p for root in flex_dirs if root.is_dir() for p in root.glob("*.flexpack")}
    states = generator_states(source_bytes)
    inventory = native_inventory(fl_roots, extras)
    effects = []
    for effect in mixer_plugin_states(source_bytes):
        checked = inspect_plugin(effect["plugin"], effect["state"], inventory, extras)
        checked.update(insert_index=effect["insert_index"], slot_index=effect["slot_index"])
        if checked["resolved_vst"]:
            recorded = vst_path(effect["state"])
            if Path(recorded).resolve() != Path(checked["resolved_vst"]):
                checked["blockers"].append({"kind": "effect_relocation", "resource": "Effect binary relocation is not yet applied to mixer state"})
        if checked["missing"] or checked["blockers"]:
            effects.append(checked)
    results = []
    for channel in document["channels"]:
        entry = {"channel_id": channel["id"], "channel_name": channel["name"],
                 "plugin": channel["plugin_internal_name"], "status": "available",
                 "missing": [], "blockers": [], "unverified": [], "resolved_sample": None,
                 "resolved_vst": None, "blocking_effects": effects}
        if channel["id"] in (midi_only or set()):
            entry["missing"].append({"kind": "user_override", "resource": "Explicit --midi-only selection"})
        sample = channel["sample_path"]
        if sample:
            candidates = []
            factory_prefix = "%FLStudioFactoryData%"
            user_prefix = "%FLStudioUserData%"
            normalized = sample.replace("\\", "/")
            if normalized.startswith(factory_prefix):
                suffix = normalized[len(factory_prefix):].lstrip("/")
                candidates += [root / suffix for root in fl_roots]
            elif normalized.startswith(user_prefix):
                suffix = normalized[len(user_prefix):].lstrip("/")
                candidates += [root / suffix for root in user_roots + extras]
            elif "%" not in normalized:
                path = Path(sample)
                candidates.append(path if path.is_absolute() else source.parent / path)
            candidates += [root / Path(normalized).name for root in extras]
            found = next((p.resolve() for p in candidates if p.is_file()), None)
            if found:
                entry["resolved_sample"] = str(found)
            else:
                entry["missing"].append({"kind": "sample", "resource": sample})
        state = states.get(channel["id"], {}).get(213, b"")
        name = channel["plugin_internal_name"] or ""
        checked = inspect_plugin(name, state, inventory, extras)
        for key in ("missing", "blockers", "unverified"):
            entry[key].extend(checked[key])
        entry["resolved_vst"] = checked["resolved_vst"]
        if not name and channel["type_raw"] not in (0, 3, 5, None):
            entry["blockers"].append({"kind": "unknown_generator", "resource": "Generator plugin identity is unavailable"})
        if name.casefold() == "flex":
            pack = flex_pack_name(state)
            if pack is None:
                entry["blockers"].append({"kind": "unknown_flex_state", "resource": "FLEX pack name cannot be decoded from this state version"})
            elif (pack + ".flexpack").casefold() not in flex_files:
                entry["missing"].append({"kind": "flex_pack", "resource": pack + ".flexpack",
                                         "searched_directories": [str(p) for p in flex_dirs]})
        entry["status"] = "midi_only" if entry["missing"] or entry["blockers"] or effects else "available"
        results.append(entry)
    return results
