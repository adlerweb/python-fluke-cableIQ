#!/usr/bin/env python3
"""Client for the Fluke Networks CableIQ (USB 0f7e:0003).

Read only: serial number, count and records of the stored measurements.
Protocol: docs/protocol.md

  cableiq.py [--lang de|en] list       list measurements
  cableiq.py dump DIR                  write raw records as .bin/.hex
  cableiq.py save FILE                 save a measurement set as JSON (load it with --set FILE)
  cableiq.py show N [--hex]            show one measurement (1 = newest)
  cableiq.py diff N1 N2                byte differences between two records
  --pcap FILE | --set FILE             work without a device

The device must not be used by another program or a VM at the same time.
"""
import argparse
import datetime
import os
import struct
import sys

from cableiq_i18n import dt, nf, reason_text, set_lang, tr, wire_text

VID, PID = 0x0F7E, 0x0003
EP_OUT, EP_IN = 0x02, 0x82
CMD_SERIAL, CMD_LOCK, CMD_COUNT, CMD_PROTO = 0x0F, 0x1F, 0x0D, 0x06
CMD_FIRST, CMD_NEXT, CMD_UNLOCK = 0x08, 0x09, 0x1E
REC_LEN = 768
RESULT_TEXT = {0: "Qualified", 1: "Disqualified", 2: "Information"}
# Autotest sequence by number of stored blocks (from comparison measurements, see docs/protocol.md)
SPEC_SETS = {
    4: ["1000BASE-T", "100BASE-TX", "Voice over IP", "Wiremap only"],
    6: ["1000BASE-T", "100BASE-TX", "10BASE-T", "Voice over IP", "Wiremap only", "Telco"],
    7: ["1000BASE-T", "100BASE-TX", "10BASE-T", "Voice over IP", "Wiremap only", "1394b S100", "Telco"],
}
# Autotests in the fixed order of the device, with the wire pairs each one uses. The low nibble of the block
# identifier (bytes 0-1 of an autotest block) is a bit mask of these pairs: bit 0-3 = pair 1-2, 3-6, 4-5, 7-8.
# Several tests share a mask, so the mask alone cannot name a test; bit 4 (0x10) and bit 8 (0x100) are set in some
# measurements and not understood yet.
TEST_PAIRS = [("1000BASE-T", 0x0F), ("100BASE-TX", 0x03), ("10BASE-T", 0x03), ("Voice over IP", 0x03),
              ("Wiremap only", 0x0F), ("1394b S100", 0x09), ("Telco", 0x06)]
TESTS_AT, TEST_LEN, TEST_MAX = 0x206, 28, 9
# "Length (termination error)" is only named for tests over all four pairs (empirical, see the protocol documentation)
FOUR_PAIR_TESTS = {"1000BASE-T", "Wiremap only"}
NVP, UNIT_NS = 0.70, 1 / 8  # delay in 1/8 ns, NVP 70 %
C_M_NS = 0.3


class DeviceError(Exception):
    """Device not found or not responding."""


def frame(cmd, data=b""):
    body = bytes([cmd, 0]) + data
    return b"\x5c\x3c" + body.replace(b"\x5c", b"\x5c\x5c") + b"\x5c\x3e"


def parse_frame(buf):
    """Returns (content without escaping, remaining bytes), or None while the frame is incomplete."""
    i, cur = 0, None
    while i < len(buf) - 1:
        a, b = buf[i], buf[i + 1]
        if a == 0x5C:
            if b == 0x3C:
                cur = bytearray()
                i += 2
                continue
            if b == 0x3E and cur is not None:
                return bytes(cur), buf[i + 2:]
            if b == 0x5C and cur is not None:
                cur.append(0x5C)
                i += 2
                continue
        if cur is not None:
            cur.append(a)
        i += 1
    return None


class UsbTransport:
    def __init__(self, timeout=5000):
        import usb.core
        import usb.util
        self.timeout = timeout
        self.dev = usb.core.find(idVendor=VID, idProduct=PID)
        if self.dev is None:
            raise DeviceError(tr("CableIQ not found (check the USB connection; is the device in use by another program or a VM?)"))
        try:
            if self.dev.is_kernel_driver_active(0):
                self.dev.detach_kernel_driver(0)
        except (NotImplementedError, usb.core.USBError):
            pass
        self.dev.set_configuration()
        usb.util.claim_interface(self.dev, 0)
        self._usb = usb
        for ep in (EP_OUT, EP_IN):  # reset toggle/halt state left by an earlier session
            self.dev.clear_halt(ep)
        self._flush()

    def _flush(self):
        """Discard responses left over from an earlier session."""
        while True:
            try:
                self.dev.read(EP_IN, 64, 300)
            except self._usb.core.USBTimeoutError:
                return

    def send(self, cmd):
        self.dev.write(EP_OUT, frame(cmd), self.timeout)

    def recv(self):
        buf = b""
        while True:
            buf += bytes(self.dev.read(EP_IN, 64, self.timeout))
            r = parse_frame(buf)
            if r:
                return r[0]

    def close(self):
        self._usb.util.dispose_resources(self.dev)


class ReplayTransport:
    """Replays the responses of a usbmon capture (LINKTYPE_USB_LINUX)."""

    def __init__(self, path):
        d = open(path, "rb").read()[24:]
        o, in_bytes, self.resp = 0, b"", []
        while o + 16 <= len(d):
            _, _, cl, _ = struct.unpack_from("<IIII", d, o)
            o += 16
            b = d[o:o + cl]
            o += cl
            if chr(b[8]) == "C" and b[10] & 0x80 and struct.unpack_from("<i", b, 28)[0] == 0:
                in_bytes += b[48:]
        while (r := parse_frame(in_bytes)):
            self.resp.append(r[0])
            in_bytes = r[1]
        self.last = None

    def send(self, cmd):
        self.last = cmd

    def recv(self):
        want = {CMD_SERIAL: 0x10, CMD_LOCK: 0x16, CMD_COUNT: 0x0E, CMD_PROTO: 0x07,
                CMD_FIRST: 0x0A, CMD_NEXT: 0x0A, CMD_UNLOCK: 0x16}.get(self.last)
        if want is None:
            raise TimeoutError("keine Antwort")
        for i, f in enumerate(self.resp):
            if f[0] == want:
                return self.resp.pop(i)
        raise TimeoutError("Mitschnitt enthaelt keine Antwort mehr")

    def close(self):
        pass


class Record:
    def __init__(self, raw):
        self.raw = raw
        self.ts = struct.unpack_from("<I", raw, 0)[0]
        self.name = raw[4:0x3A].split(b"\0")[0].decode("latin-1")
        self.version = raw[0xAC:0xB4].split(b"\0")[0].decode("latin-1")
        self.serial = raw[0xB6:0xBE].split(b"\0")[0].decode("latin-1")
        self.delays = tuple(struct.unpack_from("<H", raw, 0x140 + 4 * i)[0] for i in range(4))

    # Wiremap (interpreted from comparison measurements, "crossed" not verified yet):
    #   0x114: 9x u16, per wire 1-8 and shield: bit mask of the far-end pins (bit 0-7 = pin 1-8, bit 8 = shield)
    #   0x12A: 9x u16, short circuits at the near end in the same encoding
    @property
    def far(self):
        return [struct.unpack_from("<H", self.raw, 0x114 + 2 * i)[0] for i in range(9)]

    @property
    def shorts(self):
        return [struct.unpack_from("<H", self.raw, 0x12A + 2 * i)[0] for i in range(9)]

    @property
    def remote_id(self):
        """Remote ID (0 = none, 1-6); 0xff = nothing detected (interpretation, see docs/protocol.md)."""
        return self.raw[0x106]

    @staticmethod
    def _pins(mask):
        return [("S" if b == 8 else str(b + 1)) for b in range(9) if mask >> b & 1]

    WIRE_NAMES = list("12345678") + ["S"]

    @property
    def wires(self):
        """Per wire 1-8 and shield: name, far (pins of the far end), shorts (short circuit with), state, text.

        state: "ok" | "open" | "wrong" (the wire shows up on another or an additional pin).
        """
        out = []
        mask = struct.unpack_from("<H", self.raw, 0x204)[0]  # errors reported by the device (bit 0-7 wire 1-8, bit 8 shield)
        for i, name in enumerate(self.WIRE_NAMES):
            f, k = self.far[i], self.shorts[i]
            state = "ok" if f == 1 << i else "open" if f == 0 else "wrong"
            far, sh = self._pins(f), self._pins(k)
            txt = "ok" if state == "ok" else "open" if state == "open" else "-> " + ",".join(far)
            if sh:
                txt += "  Kurzschluss mit " + ",".join(sh)
            out.append({"name": name, "far": far, "shorts": sh, "state": state, "text": txt,
                        "fault": bool(mask >> i & 1)})
        return out

    @property
    def no_remote(self):
        """True if no far end was detected (no remote ID and no wire with a far end)."""
        return self.remote_id in (0, 0xFF) and not any(self.far)

    @property
    def wiremap_ok(self):
        """True if the device reports no wiremap error for wires 1-8 (shield separately, see shield_ok)."""
        return not any(w["fault"] for w in self.wires[:8])

    @property
    def shield_ok(self):
        w = self.wires[8]
        return not w["fault"]

    @property
    def remote_text(self):
        rid = self.remote_id
        return "none" if rid in (0, 0xFF) else str(rid)

    def wiremap_text(self):
        return "\n".join(f"  {w["name"]}: {w["text"]}" for w in self.wires)

    @property
    def time(self):
        # the time is stored as local time -> represent it without a time zone
        return datetime.datetime.fromtimestamp(self.ts, datetime.timezone.utc).replace(tzinfo=None)

    @property
    def result(self):
        """Overall result (byte 0x200: 0 qualified, 1 disqualified, 2 information)."""
        return RESULT_TEXT.get(self.raw[0x200], f"Unbekannt ({self.raw[0x200]})")

    @property
    def device_length(self):
        """Length according to the device in m (field 0x100) and the "approximate" flag (bit 15)."""
        v = struct.unpack_from("<H", self.raw, 0x100)[0]
        return (v & 0x7FFF) * UNIT_NS * C_M_NS * NVP, bool(v & 0x8000)

    @property
    def autotests(self):
        """Autotests with result: list of name, qualified, reason.

        One 28-byte block per autotest from 0x206 (the list ends at identifier 0). Block byte 2 = 0: passed, else
        not; bytes 3/4/5 = wiremap/length/signal result; only the value 1 is a reason for failure (wording taken
        from the reference values). The values 2 and 3 mean "not checked/not applicable" and give no reason.
        """
        blocks = []
        for k in range(TEST_MAX):
            o = TESTS_AT + TEST_LEN * k
            if o + TEST_LEN > len(self.raw) or self.raw[o:o + 2] == b"\0\0":
                break
            blocks.append(self.raw[o:o + TEST_LEN])
        names = autotest_names([b[0] for b in blocks])
        out = []
        for name, b in zip(names, blocks):
            reasons = []
            if b[2]:
                for val, err, only4 in ((b[3], "Wiremap", False), (b[4], "Length (termination error)", True),
                                        (b[5], "Impedance error", False)):
                    if val == 1 and (name in FOUR_PAIR_TESTS or not only4):
                        reasons.append(err)
            out.append({"name": name, "qualified": b[2] == 0, "reason": "; ".join(reasons)})
        return out

    @property
    def operator_lines(self):
        """The two "Tested by" fields from the device (0x3A and 0x60, 38 bytes each); "=" (placeholder) becomes ""."""
        out = []
        for o in (0x3A, 0x60):
            t = self.raw[o:o + 38].split(b"\0")[0].decode("latin-1").strip()
            out.append("" if t == "=" else t)
        return out

    @property
    def operator_fields(self):
        """Non-empty "Tested by" fields."""
        return [t for t in self.operator_lines if t]

    @property
    def qualified_names(self):
        return [t["name"] for t in self.autotests if t["qualified"]]

    @property
    def delays_ns(self):
        """Delay per pair in nanoseconds (raw value in 1/8 ns)."""
        return [d * UNIT_NS for d in self.delays]

    @property
    def lengths(self):
        return [d * UNIT_NS * C_M_NS * NVP for d in self.delays]


def _name_candidates(masks, start=0, limit=2):
    """Assignments of the blocks to TEST_PAIRS (in order, tests may be skipped) whose pair masks fit; at most `limit`."""
    if not masks:
        return [[]]
    out = []
    for i in range(start, len(TEST_PAIRS)):
        name, pairs = TEST_PAIRS[i]
        if pairs == masks[0] & 0x0F:
            out += [[name] + rest for rest in _name_candidates(masks[1:], i + 1, limit - len(out))]
            if len(out) >= limit:
                break
    return out


def autotest_names(masks):
    """Names of the autotests from the identifier masks of the stored blocks.

    A block count seen on real devices (SPEC_SETS) is trusted if the masks fit. For other counts the names are only
    guessed when exactly one assignment in the fixed test order fits the masks; otherwise "Autotest N" is used.
    """
    known = SPEC_SETS.get(len(masks))
    if known and all(dict(TEST_PAIRS)[n] == m & 0x0F for n, m in zip(known, masks)):
        return list(known)
    found = _name_candidates(masks)
    if len(found) == 1:
        return found[0]
    return [f"Autotest {i + 1}" for i in range(len(masks))]


def hexdump(b, base=0):
    for i in range(0, len(b), 16):
        c = b[i:i + 16]
        print(f"{base + i:04x}  {c.hex(" "):47s}  {"".join(chr(x) if 32 <= x < 127 else "." for x in c)}")


def read_all(t, progress=None):
    """Sequence: serial, lock, count, protocol, records, unlock.

    Lock: the device shows "USB connected" and releases its memory for reading; unlock ends the access.

    progress(read, total) is called after every record.
    """
    t.send(CMD_SERIAL)
    serial = t.recv()[2:].split(b"\0")[0].decode()
    t.send(CMD_LOCK)
    t.recv()
    try:
        t.send(CMD_COUNT)
        count = struct.unpack_from("<H", t.recv(), 2)[0]
        t.send(CMD_PROTO)
        t.recv()
        recs = []
        t.send(CMD_FIRST)
        while len(f := t.recv()) > 2:
            if len(f) - 2 != REC_LEN:
                print(tr("Warning: record length {n}").format(n=len(f) - 2), file=sys.stderr)
            recs.append(Record(f[2:]))
            if progress:
                progress(len(recs), count)
            t.send(CMD_NEXT)
    finally:
        try:
            t.send(CMD_UNLOCK)
            t.recv()  # acknowledgement "16 00 00 00"; if unread it stays in the device
        except Exception as e:  # unlock ends the PC access to the device; errors are not fatal
            print(tr("Unlock failed: {e}").format(e=e), file=sys.stderr)
    if count != len(recs):
        print(tr("Warning: device reports {a}, received {b}").format(a=count, b=len(recs)), file=sys.stderr)
    return serial, recs


def main():
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--lang")
    set_lang(pre.parse_known_args()[0].lang)  # set the language before the help texts are built
    ap = argparse.ArgumentParser(description=tr("Fluke Networks CableIQ: read stored measurements (read-only)."))
    ap.add_argument("--lang", choices=["auto", "de", "en"], help=tr("output language (default: from the environment)"))
    ap.add_argument("--pcap", help=tr("use a capture instead of the device"))
    ap.add_argument("--set", help=tr("use a saved measurement set (JSON) instead of the device"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help=tr("list measurements"))
    p = sub.add_parser("dump", help=tr("write raw records as .bin/.hex"))
    p.add_argument("dir")
    p = sub.add_parser("save", help=tr("save measurements as a set (JSON); load later with --set"))
    p.add_argument("file")
    p = sub.add_parser("show", help=tr("show one measurement (1 = newest)"))
    p.add_argument("nr", type=int)
    p.add_argument("--hex", action="store_true")
    p = sub.add_parser("diff", help=tr("byte differences between two records"))
    p.add_argument("a", type=int)
    p.add_argument("b", type=int)
    a = ap.parse_args()

    if a.set:
        import cableiq_store
        try:
            s = cableiq_store.load_set(a.set)
        except cableiq_store.StoreError as e:
            sys.exit(str(e))
        serial, recs = s["serial"], s["recs"]
    else:
        try:
            t = ReplayTransport(a.pcap) if a.pcap else UsbTransport()
        except DeviceError as e:
            sys.exit(str(e))
        try:
            serial, recs = read_all(t)
        finally:
            t.close()

    def get(n):
        if not 1 <= n <= len(recs):
            sys.exit(tr("Record {n} does not exist (1..{m})").format(n=n, m=len(recs)))
        return recs[n - 1]

    if a.cmd == "list":
        print(tr("Serial number {s}, {n} measurements").format(s=serial, n=len(recs)))
        print(f"{"#":>2}  {tr("Cable ID"):20s} {tr("Date/time"):19s} {tr("Length 12/36/45/78 (m)"):26s} "
              f"{tr("Version")}")
        for i, r in enumerate(recs, 1):
            L = " / ".join(f"{nf(x, 1):>5s}" for x in r.lengths)
            print(f"{i:2d}  {r.name:20s} {dt(r.time):19s} {L:26s} {r.version}")
    elif a.cmd == "save":
        import cableiq_store
        try:
            cableiq_store.save_set(a.file, serial, recs)
        except cableiq_store.StoreError as e:
            sys.exit(str(e))
        print(tr("{n} measurements saved to {f}").format(n=len(recs), f=a.file))
    elif a.cmd == "dump":
        os.makedirs(a.dir, exist_ok=True)
        for i, r in enumerate(recs, 1):
            base = os.path.join(a.dir, f"{i:02d}")
            open(base + ".bin", "wb").write(r.raw)
            with open(base + ".hex", "w") as f:
                f.write(f"# {r.name} {r.time:%Y-%m-%d %H:%M:%S}\n")
                for o in range(0, len(r.raw), 16):
                    f.write(f"{o:04x}  {r.raw[o:o + 16].hex(" ")}\n")
        print(tr("{n} records written to {d}").format(n=len(recs), d=a.dir))
    elif a.cmd == "show":
        r = get(a.nr)
        print(f"{r.name}  {dt(r.time)}  " + tr("Device {s} {v}").format(s=r.serial, v=r.version))
        print(tr("Delay (ns):"), " ".join(nf(x, 3) for x in r.delays_ns), " ", tr("Length (m):"),
              " ".join(nf(x, 1) for x in r.lengths))
        print(tr("Result:"), tr(r.result), "|", tr("Qualified:"),
              "; ".join(tr(n) for n in r.qualified_names) or "-")
        for t in r.autotests:
            res = tr("Qualified") if t["qualified"] else tr("Disqualified")
            print(f"  {tr(t["name"]):15s} {res:16s} {reason_text(t["reason"])}")
        print(tr("Remote ID:"), tr("none") if r.remote_text == "none" else r.remote_text)
        print(tr("Wiremap (wire: far end):"))
        for w in r.wires:
            print(f"  {w["name"]}: {wire_text(w)}")
        if a.hex:
            hexdump(r.raw)
    elif a.cmd == "diff":
        x, y = get(a.a).raw, get(a.b).raw
        diff = [i for i in range(REC_LEN) if x[i] != y[i]]
        print(tr("{n} of {m} bytes differ").format(n=len(diff), m=REC_LEN))
        for i in diff:
            print(f"  0x{i:03x}: {x[i]:02x} -> {y[i]:02x}")


if __name__ == "__main__":
    main()
