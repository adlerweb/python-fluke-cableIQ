"""Save and load a measurement set (JSON, versioned).

A measurement set contains everything that belongs to one read-out:
  - serial number of the device and time of saving
  - the raw records (768 bytes per measurement, base64), from which all values can be recomputed
  - per measurement the changed "Tested by" lines (only if different from the device value) and a note
  - optionally the report details (location, default for the person who tested, logo as an image file)
"""
import base64
import datetime
import json
import os
from pathlib import Path

import cableiq
from cableiq_i18n import tr

FORMAT = "cableiq-messsatz"
VERSION = 1
MAX_LOGO = 5 * 1024 * 1024


class StoreError(Exception):
    """File not readable, not a measurement set, or damaged."""


def save_set(path, serial, recs, ops=None, protocol=None, logo_path="", notes=None):
    """Writes the measurement set atomically to `path`.

    ops: list (same length as recs) with changed "Tested by" lines, or None per measurement.
    protocol: dict with the optional keys "location" and "tester".
    notes: list (same length as recs) with notes per measurement (None or "" = none).
    """
    notes = notes or [None] * len(recs)
    if len(notes) != len(recs):
        raise StoreError(tr("ops and recs differ in length"))
    ops = ops or [None] * len(recs)
    if len(ops) != len(recs):
        raise StoreError(tr("ops and recs differ in length"))
    data = {
        "format": FORMAT,
        "version": VERSION,
        "saved": datetime.datetime.now().isoformat(timespec="seconds"),
        "device": {"serial": serial, "vid": cableiq.VID, "pid": cableiq.PID},
        "records": [],
    }
    for r, o, n in zip(recs, ops, notes):
        item = {"raw": base64.b64encode(r.raw).decode("ascii"),
                # only a hint when reading the file; everything is recomputed from "raw" on load
                "name": r.name, "time": f"{r.time:%Y-%m-%d %H:%M:%S}"}
        if o is not None:
            item["operators"] = list(o)
        if n:
            item["note"] = str(n)
        data["records"].append(item)
    proto = {k: v for k, v in (protocol or {}).items() if v}
    if logo_path:
        p = Path(logo_path)
        try:
            blob = p.read_bytes()
        except OSError:
            blob = b""
        if blob and len(blob) <= MAX_LOGO:
            proto["logo"] = {"name": p.name, "data": base64.b64encode(blob).decode("ascii")}
    if proto:
        data["protocol"] = proto
    tmp = str(path) + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except OSError as e:
        raise StoreError(tr("The file could not be written: {e}").format(e=e)) from e


def load_set(path):
    """Reads a measurement set. Returns a dict with serial, saved, recs, ops, protocol, logo (name, bytes) or None."""
    try:
        data = json.loads(Path(path).read_text("utf-8"))
    except (OSError, ValueError) as e:
        raise StoreError(tr("File not readable: {e}").format(e=e)) from e
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise StoreError(tr("This is not a CableIQ measurement set."))
    if not isinstance(data.get("version"), int) or data["version"] > VERSION:
        raise StoreError(tr("Unknown file version {v} (supported up to {m}).").format(v=repr(data.get("version")), m=VERSION))
    try:
        serial = str(data["device"]["serial"])
        recs, ops, notes = [], [], []
        for i, item in enumerate(data["records"], 1):
            raw = base64.b64decode(item["raw"], validate=True)
            if len(raw) != cableiq.REC_LEN:
                raise StoreError(tr("Measurement {i}: record has {n} instead of {m} bytes.").format(i=i, n=len(raw), m=cableiq.REC_LEN))
            recs.append(cableiq.Record(raw))
            o = item.get("operators")
            if o is not None:
                if not (isinstance(o, list) and all(isinstance(x, str) for x in o)):
                    raise StoreError(tr("Measurement {i}: invalid 'operators' entry.").format(i=i))
                o = (o + ["", ""])[:2]
            ops.append(o)
            n = item.get("note", "")
            if not isinstance(n, str):
                raise StoreError(tr("Measurement {i}: invalid 'note' entry.").format(i=i))
            notes.append(n)
        proto = data.get("protocol") or {}
        logo = None
        if isinstance(proto.get("logo"), dict):
            blob = base64.b64decode(proto["logo"]["data"], validate=True)
            if len(blob) <= MAX_LOGO:
                logo = (os.path.basename(str(proto["logo"].get("name") or "logo")), blob)
    except StoreError:
        raise
    except (KeyError, TypeError, ValueError) as e:
        raise StoreError(tr("Measurement set is damaged: {e}").format(e=repr(e))) from e
    return {"serial": serial, "saved": data.get("saved", ""), "recs": recs, "ops": ops, "notes": notes,
            "protocol": {k: str(proto[k]) for k in ("location", "tester") if proto.get(k)}, "logo": logo}
