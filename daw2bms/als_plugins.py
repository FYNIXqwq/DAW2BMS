"""Read-only Live plug-in inventory and per-load evidence, never name substitution."""
from __future__ import annotations

from collections import Counter
import os
from pathlib import Path
import re
import sqlite3
import uuid
from urllib.parse import parse_qs

from .als import AlsError, value
from .i18n import msg


def plugin_requirements(node):
    requirements = []
    for device in node.iter("PluginDevice"):
        desc = device.find("PluginDesc")
        info = list(desc) if desc is not None else []
        if len(info) != 1 or info[0].tag not in ("VstPluginInfo", "Vst3PluginInfo"):
            raise AlsError(msg("Unsupported or unidentified Ableton plug-in format; MIDI is preserved."))
        info = info[0]
        name = value(info, "Name") or value(info, "PlugName") or "PluginDevice"
        try:
            if info.tag == "Vst3PluginInfo":
                fields = [int(value(info, f"Uid/Fields.{i}")) for i in range(4)]
                if any(not -(1 << 31) <= x < (1 << 32) for x in fields):
                    raise ValueError()
                identity = str(uuid.UUID(hex="".join(f"{x & 0xffffffff:08x}" for x in fields)))
                kind = "vst3"
            else:
                unique_id = int(value(info, "UniqueId"))
                if not -(1 << 31) <= unique_id < (1 << 32):
                    raise ValueError()
                identity, kind = str(unique_id & 0xffffffff), "vst"
        except (ValueError, TypeError, AttributeError) as exc:
            raise AlsError(msg("Cannot identify Ableton plug-in {p0}; MIDI is preserved.", p0=name)) from exc
        requirements.append({"format": kind, "identity": identity, "name": name,
                             "shell": value(info, "IsShellClient", "false") == "true"})
    return requirements


def inventory_path():
    return Path(os.environ.get("LOCALAPPDATA", "")) / "Ableton/Live Database/Live-plugins-1.db"


def read_inventory(path=None):
    path = Path(path) if path is not None else inventory_path()
    try:
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2) as db:
            version = db.execute("SELECT version, platform FROM version").fetchone()
            if version != (1, 1):
                raise sqlite3.DatabaseError("Unsupported Live Windows plugin database schema")
            db.row_factory = sqlite3.Row
            rows = db.execute("""SELECT p.dev_identifier,p.name,p.scanstate,p.enabled,
                m.path,m.scanstate AS module_scanstate,m.arch,
                EXISTS(SELECT 1 FROM plugin_domains d WHERE d.module_id=m.module_id AND d.enabled=1) AS domain_enabled
                FROM plugins p JOIN plugin_modules m USING(module_id)""").fetchall()
            return [dict(r) for r in rows]
    except (sqlite3.Error, OSError) as exc:
        raise AlsError(msg("Ableton plug-in scan database is unavailable. Enable and scan plug-ins in Live; MIDI is preserved.")) from exc


def identifier_parts(text):
    match = re.fullmatch(r"device:(vst3|vst):[^:]+:([^?]+)(?:\?.*)?", text)
    if not match:
        return None
    kind, ident = match.groups()
    try:
        ident = str(uuid.UUID(ident)) if kind == "vst3" else str(int(ident) & 0xffffffff)
    except ValueError:
        return None
    return kind, ident


def verify_inventory(requirements, rows=None):
    if not requirements:
        return []
    rows = read_inventory() if rows is None else rows
    verified = []
    for req in requirements:
        matches = [r for r in rows if identifier_parts(r["dev_identifier"]) == (req["format"], req["identity"])]
        if req.get("shell"):
            matches = [r for r in matches if parse_qs(r["dev_identifier"].partition("?")[2]).get("n") == [req["name"]]]
        usable = [r for r in matches if r["enabled"] == 1 and r["scanstate"] == 1
                  and r["module_scanstate"] == 1 and r["arch"] == (3 if req["format"] == "vst3" else 2) and r["domain_enabled"] == 1
                  and Path(r["path"]).exists()]
        if not usable:
            raise AlsError(msg("Ableton plug-in {p0} ({p1}) is missing, disabled or failed its scan; MIDI is preserved.", p0=req["name"], p1=req["identity"]))
        # Name is recorded for exact Live log matching, never used as identity.
        verified.append({**req, "loaded_name": usable[0]["name"], "module": usable[0]["path"]})
    return verified


def verify_load_log(text, project, requirements):
    """Require this Set's load marker and a fresh success for every instance.

    VST3 CID proof ties the success to the requested ID. VST2 names are only
    accepted after ID-based scan preflight and exact instance counting.
    Unknown Live logging formats fail closed rather than accepting bypass audio.
    """
    marker = 'Loading document "' + str(Path(project).resolve()) + '"'
    pos = text.rfind(marker)
    if pos < 0:
        raise AlsError(msg("Cannot verify this Ableton Set's plug-in load log; MIDI is preserved."))
    section = text[pos:]
    # An unrelated Set switch invalidates the evidence.
    if 'Loading document "' in section[len(marker):]:
        raise AlsError(msg("Cannot verify this Ableton Set's plug-in load log; MIDI is preserved."))
    # Live logs optional bus-deactivation refusals as errors even when the
    # processor subsequently loads and its preset is restored successfully.
    diagnostic = "\n".join(line for line in section.splitlines() if not re.search(
        r"VST3: plugin processor (?:input|output) audio bus \d+ could not be deactivated \(error: false\)", line))
    failure = re.search(r"(?im)^.*(?:error:.*(?:VST|plug.?in)|(?:VST|plug.?in).*\b(?:failed|not found|could not load|failed to restore)\b).*$", diagnostic)
    if failure:
        raise AlsError(msg("Ableton reported a plug-in load failure: {p0}. MIDI is preserved.", p0=failure.group(0)[:1000]))
    cids = Counter(x.lower() for x in re.findall(r"VST3: plugin processor successfully loaded: .*?\(cid: \{([0-9a-fA-F-]+)\}\)", section))
    created = Counter(("vst3" if kind.lower() == "vst3" else "vst", name.strip())
                      for kind, name in re.findall(r"(?im)info: (VST3|VST2|VST): Restored: ([^\r\n]+)", section))
    required = Counter((r["format"], r["loaded_name"]) for r in requirements)
    required_cids = Counter(r["identity"] for r in requirements if r["format"] == "vst3")
    if any(created[k] < count for k, count in required.items()) or any(cids[k] < count for k, count in required_cids.items()):
        raise AlsError(msg("Cannot confirm all Ableton plug-in instances loaded successfully; MIDI is preserved."))
    module_paths = {Path(p).resolve() for p in re.findall(r'(?im)info: (?:VST2|VST): Plugin Path: "([^"\r\n]+)"', section)}
    if any(Path(r["module"]).resolve() not in module_paths for r in requirements if r["format"] == "vst"):
        raise AlsError(msg("Cannot confirm all Ableton plug-in instances loaded successfully; MIDI is preserved."))
    return {"instances": len(requirements), "method": "fresh_set_log_and_scanned_plugin_ids", "plugins": requirements}


def log_paths():
    base = Path(os.environ.get("APPDATA", "")) / "Ableton"
    return list(base.glob("Live */Preferences/Log.txt"))


def verify_live_log(project, requirements, offsets):
    return verify_load_log(read_live_load_log(project, offsets), project, requirements)


def read_live_load_log(project, offsets):
    marker = 'Loading document "' + str(Path(project).resolve()) + '"'
    for path in sorted(log_paths(), key=lambda p: p.stat().st_mtime, reverse=True):
        size = path.stat().st_size
        offset = offsets.get(str(path), 0)
        if size < offset:
            offset = 0
        with path.open("rb") as stream:
            stream.seek(max(offset, size - 4 * 1024 * 1024))
            text = stream.read(4 * 1024 * 1024).decode("utf-8", errors="replace")
        if marker in text:
            return text
    raise AlsError(msg("Cannot verify this Ableton Set's plug-in load log; MIDI is preserved."))
