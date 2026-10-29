"""Max for Live file preflight and read-only runtime verification via AbletonMCP."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import socket
import time
import xml.etree.ElementTree as ET

from .als import AlsError, value
from .i18n import msg
from .keysounds import sha256_file

MAX_TYPES = frozenset(("MxDeviceInstrument", "MxDeviceAudioEffect", "MxDeviceMidiEffect"))


def devices(node):
    for element in node.iter():
        if element.tag.startswith("MxDevice"):
            if element.tag not in MAX_TYPES:
                raise AlsError(msg("Unsupported Max for Live device structure: {p0}; MIDI is preserved.", p0=element.tag))
            yield element


def _resolve(ref, source, roots, *, amxd=False):
    absolute = value(ref, "Path", "")
    relative = value(ref, "RelativePath", "")
    name = value(ref, "Name", "")
    if not relative:
        parts = [e.get("Dir", "") for e in ref.findall("RelativePath/RelativePathElement")]
        if parts or name:
            relative = str(Path(*parts) / name)
    if absolute and Path(absolute).is_file():
        choices = {Path(absolute).resolve()}
    else:
        bases = [source.parent, *roots]
        bases += [p for p in source.parents if (p / "Ableton Project Info").is_dir()]
        choices = {(base / relative).resolve() for base in bases if relative and (base / relative).is_file()}
    if len(choices) != 1:
        raise AlsError(msg("Missing or ambiguous Max for Live file: {p0}; MIDI is preserved.", p0=absolute or relative or "FileRef"))
    path = choices.pop()
    if amxd:
        with path.open("rb") as stream:
            header = stream.read(8)
        if path.suffix.lower() != ".amxd" or header[:4] != b"ampf" or path.stat().st_size < 12:
            raise AlsError(msg("Invalid Max for Live device file: {p0}; MIDI is preserved.", p0=path))
    return path


def prepare_max(node, source, roots):
    # Only mutate the caller's generated copy; opaque parameters/blobs stay intact.
    for device in devices(node):
        refs = device.findall("PatchSlot/Value/MxPatchRef/FileRef")
        if len(refs) != 1:
            raise AlsError(msg("Unsupported Max for Live device structure: {p0}; MIDI is preserved.", p0=device.tag))
        mapped = device.find("IdRefList/IdRefList")
        routing = [e.get("Value", "") for e in device.findall("Routables/.//Target")]
        if (mapped is not None and len(mapped)) or any(p and not p.endswith("/None") for p in routing):
            raise AlsError(msg("Max for Live device {p0} uses cross-device mappings or routing; MIDI is preserved.", p0=value(device, "UserName") or device.tag))
        for ref in refs + device.findall("FileDropList/.//FileRef"):
            path = _resolve(ref, source, roots, amxd=ref is refs[0])
            for tag, text in (("Path", str(path)), ("RelativePath", ""), ("RelativePathType", "0")):
                child = ref.find(tag)
                if child is None: child = ET.SubElement(ref, tag)
                child.clear(); child.set("Value", text)


def max_requirements(root):
    """Keep owner and nested-chain locations so equal names cannot match wrong devices."""
    result = []
    def walk(container, location):
        if container is None: return
        for index, device in enumerate(container):
            here = location + [index]
            if device.tag in MAX_TYPES:
                path = Path(value(device, "PatchSlot/Value/MxPatchRef/FileRef/Path", ""))
                if not path.is_file():
                    raise AlsError(msg("Missing or ambiguous Max for Live file: {p0}; MIDI is preserved.", p0=path))
                params = []
                visible_index = 0
                for parameter in device.findall("ParameterList/ParameterList/*"):
                    name, raw = value(parameter, "Name"), value(parameter, "Timeable/Manual")
                    if raw is None: raw = value(parameter, "Manual")
                    if raw is None: continue
                    try:
                        number = float(raw)
                        if not name or not math.isfinite(number): raise ValueError()
                    except (ValueError, TypeError) as exc:
                        raise AlsError(msg("Unsupported Max for Live device structure: {p0}; MIDI is preserved.", p0=path.name)) from exc
                    if name and math.isfinite(number):
                        visible_index += 1
                        if value(parameter, "IsStored", "true") == "false": continue
                        # The XML Index includes hidden Max-only controls. Live's
                        # public parameter list contains the Timeable subset.
                        expected = {"name": name, "value": number, "index": visible_index}
                        short = value(parameter, "ShortName")
                        if short and short != name: expected["short_name"] = short
                        params.append(expected)
                if not params:
                    raise AlsError(msg("Max for Live device {p0} has no verifiable stored parameters; MIDI is preserved.", p0=path.name))
                files = [path] + [Path(value(ref, "Path", "")) for ref in device.findall("FileDropList/.//FileRef")]
                result.append({"location": here, "class_name": device.tag,
                    "name": value(device, "UserName") or path.stem, "parameters": params,
                    "parameter_count": visible_index + 1,
                    "device_on": value(device, "On/Manual", "true") == "true",
                    "files": [{"path": str(p.resolve()), "sha256": sha256_file(p)} for p in files],
                    "state_sha256": hashlib.sha256(ET.tostring(device, encoding="utf-8")).hexdigest()})
            for group, kind in (("Branches", "chains"), ("ReturnBranches", "return_chains")):
                for chain_index, branch in enumerate(device.findall(group + "/*")):
                    nested = branch.find("DeviceChain/Devices")
                    if nested is None: nested = branch.find("DeviceChain/*/Devices")
                    walk(nested, here + [kind, chain_index])
    live = root.find("LiveSet")
    track_index = return_index = 0
    for track in live.findall("Tracks/*"):
        kind = "return_tracks" if track.tag == "ReturnTrack" else "tracks"
        index = return_index if kind == "return_tracks" else track_index
        walk(track.find("DeviceChain/DeviceChain/Devices"), [kind, index])
        if kind == "return_tracks": return_index += 1
        else: track_index += 1
    master = live.find("MainTrack")
    if master is None: master = live.find("MasterTrack")
    if master is not None: walk(master.find("DeviceChain/DeviceChain/Devices"), ["master_track"])
    if len(result) != sum(1 for _ in devices(root)):
        raise AlsError(msg("Unsupported Max for Live device structure: {p0}; MIDI is preserved.", p0="device location"))
    return result


def bridge_read(command, params=None, *, timeout=5):
    """Bounded localhost read-only subset of the installed AbletonMCP protocol."""
    if command not in ("get_script_info", "get_session_snapshot"):
        raise ValueError("Read-only bridge command required")
    try:
        with socket.create_connection(("127.0.0.1", 9877), timeout=timeout) as client:
            client.settimeout(timeout)
            client.sendall(json.dumps({"type": command, "params": params or {}}).encode("utf-8"))
            data = bytearray()
            deadline = time.monotonic() + timeout
            while len(data) < 16 * 1024 * 1024 and time.monotonic() < deadline:
                client.settimeout(max(.01, deadline-time.monotonic()))
                chunk = client.recv(65536)
                if not chunk: break
                data.extend(chunk)
                try: response = json.loads(data)
                except (ValueError, UnicodeError): continue
                if response.get("status") != "success" or not isinstance(response.get("result"), dict): break
                return response["result"]
    except OSError as exc:
        raise AlsError(msg("Max for Live verification requires the AbletonMCP Remote Script enabled in Live; MIDI is preserved.")) from exc
    raise AlsError(msg("Max for Live verification requires the AbletonMCP Remote Script enabled in Live; MIDI is preserved."))


def verify_bridge():
    info = bridge_read("get_script_info")
    if info.get("protocol_version") != 1 or info.get("snapshot_schema") != "ableton_mcp_snapshot_v2" or "get_session_snapshot" not in info.get("capabilities", []):
        raise AlsError(msg("Max for Live verification requires the AbletonMCP Remote Script enabled in Live; MIDI is preserved."))


def verify_files(requirements):
    for req in requirements:
        for file in req["files"]:
            path = Path(file["path"])
            if not path.is_file() or sha256_file(path) != file["sha256"]:
                raise AlsError(msg("Max for Live file changed or disappeared: {p0}; MIDI is preserved.", p0=path))


def verify_snapshot(snapshot, requirements, clip_names):
    if snapshot.get("schema") != "ableton_mcp_snapshot_v2": return False
    actual = Counter(c.get("name") for t in snapshot.get("tracks", []) for c in t.get("arrangement_clips", []))
    if actual != Counter(clip_names): return False
    for req in requirements:
        path = list(req["location"])
        try:
            kind = path.pop(0)
            owner = snapshot[kind] if kind == "master_track" else snapshot[kind][path.pop(0)]
            device = owner["devices"][path.pop(0)]
            while path:
                chain_kind, chain_index, device_index = path[:3]; del path[:3]
                chain = next(c for c in device["chains"] if c["kind"] == chain_kind and c["index"] == chain_index)
                device = chain["devices"][device_index]
            if device["class_name"] != req["class_name"] or device["name"] != req["name"]: return False
            parameters = device["parameters"]
            if len(parameters) != req["parameter_count"]: return False
            if not parameters or not math.isclose(parameters[0]["value"], float(req["device_on"]), abs_tol=1e-6): return False
            for expected in req["parameters"]:
                names = {expected["name"], expected.get("short_name", expected["name"])}
                matches = [p for p in parameters[1:] if p["name"] in names
                           and ("index" not in expected or p.get("index") == expected["index"])]
                if len(matches) != 1 or not matches[0].get("is_enabled", False): return False
                if not math.isclose(matches[0]["value"], expected["value"], rel_tol=1e-5, abs_tol=1e-5): return False
        except (KeyError, TypeError, IndexError, StopIteration, ValueError): return False
    return True


def check_max_log(text, project):
    marker = 'Loading document "' + str(Path(project).resolve()) + '"'
    pos = text.rfind(marker)
    if pos < 0 or 'Loading document "' in text[pos+len(marker):]:
        raise AlsError(msg("Cannot verify this Ableton Set's plug-in load log; MIDI is preserved."))
    section = text[pos:]
    failure = re.search(r"(?im)^.*(?:error:.*(?:\bMax\b|MxD|amxd|patcher)|(?:\bMax\b|MxD|amxd|patcher).*\b(?:failed|not found|can't load|could not load|no such object)\b).*$", section)
    if failure:
        raise AlsError(msg("Max for Live reported a loading error: {p0}; MIDI is preserved.", p0=failure.group(0)[:1000]))


def wait_for_max(requirements, clip_names, *, timeout, checkpoint=lambda: None):
    verify_bridge()
    deadline = time.monotonic() + min(timeout, 30)
    stable = 0
    while time.monotonic() < deadline:
        if deadline - time.monotonic() < .5: break
        checkpoint()
        verify_files(requirements)
        snapshot = bridge_read("get_session_snapshot", {"include_notes": False, "include_params": True}, timeout=min(5, max(.1, deadline-time.monotonic())))
        stable = stable + 1 if verify_snapshot(snapshot, requirements, clip_names) else 0
        if stable >= 2:
            return {"method": "amxd_hashes_and_live_parameters", "instances": len(requirements), "devices": requirements}
        time.sleep(.25)
    raise AlsError(msg("Max for Live devices did not restore their saved parameters; MIDI is preserved."))
