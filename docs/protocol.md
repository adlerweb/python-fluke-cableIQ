# Fluke Networks CableIQ – USB protocol

Status: 2026-10-18. Result of analyzing a USB capture of reading the stored measurements, and of our own Python client (`cableiq.py`), which confirmed the protocol on the real device.

## 1. Device

| Item | Value |
|---|---|
| Device | Fluke Networks CableIQ, USB `0f7e:0003`, serial number (7 digits), firmware V1.80.00 |

## 2. USB descriptors

- Full speed, one configuration, one interface (class 255, vendor specific)
- Bulk OUT `0x02`, bulk IN `0x82`, 64 bytes each
- no control requests, no serial-number descriptor; all data runs over the bulk endpoints

## 3. Transport framing

```
5C 3C | CMD 00 | data ... | 5C 3E
```

- Every 0x5C inside the content is escaped as `5C 5C`.
- Requests are 6 bytes long (`5C 3C CMD 00 5C 3E`).
- Responses arrive in 64-byte packets; the last one is padded with zeros.
- Response command = request command + 1; only the record fetch (`08`/`09`) answers with `0A`.

## 4. Sequence of reading

| Request    | Response             | Meaning                                                                                                                                                                  |
| ---------- | -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `0F`       | `10` + `"1234567\0"` | serial number (confirmed)                                                                                                                                                |
| `1F`       | `16` + `00 00`       | lock: the device shows a message that USB is connected and allows the PC to read its memory (observed on the device display)                                             |
| `0D`       | `0E` + u16 = 15      | number of stored measurements (confirmed)                                                                                                                                |
| `06`       | `07` + u16 = 10      | unknown, probably interface/protocol version                                                                                                                             |
| `08`       | `0A` + 768 bytes     | first record (confirmed)                                                                                                                                                 |
| `09` (14×) | `0A` + 768 bytes     | next record each (confirmed)                                                                                                                                             |
| `09`       | `0A` without data    | end of list (confirmed)                                                                                                                                                  |
| `1E`       | `16` + `00 00`       | unlock: ends the PC access, the device display returns to normal (display effect as reported, not captured); the acknowledgement **must be read** (confirmed, see below) |

Records arrive from newest to oldest. One record takes about 0.9 s.

### Operating notes from our own client

- **Read acknowledgements:** `16 00 00 00` is the general acknowledgement (lock and unlock). If it is not read after `1E`, it stays in the device and shows up in the next session as the response to the first request (the "serial number" is then empty).
- **Reset the endpoints:** After one session the device stopped responding until `clear_halt` was issued on both endpoints (0x02 and 0x82). The client does this on open and then discards stale data (300 ms of reading); this allowed several sessions in a row without errors.
- The device must not be in use by another program or a VM at the same time. When it is replugged, the device number changes and the access rights (ACL or udev) have to be set again.

## 5. Record layout (768 bytes, little-endian)

| Offset | Size | Content | Status |
|---|---|---|---|
| 0x000 | u32 | timestamp (seconds since 1970, stored as local time, so read it without time-zone conversion) | confirmed |
| 0x004 | string | cable ID, Latin-1 (`0xE4` = ä, `0xFC` = ü), NUL-terminated | confirmed |
| 0x0AC | 8 bytes | firmware version, e.g. `V1.80.00` | confirmed |
| 0x0B6 | string | serial number of the device | confirmed |
| 0x03A, 0x060 | 38 bytes each | operator fields "Tested by" (text) | confirmed |
| 0x0C4 | u16 | probably NVP in percent (0x46 = 70) | assumption |
| 0x100 | u16 | **length according to the device** (delay in 1/8 ns, same conversion as below); this is the length the device itself reports. Bit 15 = approximate ("~1.8"). It is neither minimum nor maximum of the pairs but the device's own choice (Los 5: 95 = pair 36, Los 2: 77 = pair 36) | confirmed (value), rule open |
| 0x102 | 4 bytes | `51 e8 00 00` or `51 a8 00 00` (bit 6 of the second byte is cleared on open cables and the oldest records) | unknown |
| 0x106 | u8 | **remote ID** (1–6 = ID locator, 0 = none, 0xFF = nothing detected); followed by 7× `FF` | confirmed |
| 0x10E | u16 | `0x0010` if a far end was detected, else 0 | assumption |
| 0x110 | u32 | repetition of the remote ID | assumption |
| 0x114 | 9× u16 | **wiremap, far end**, per wire 1–8 and shield (S) | confirmed |
| 0x12A | 9× u16 | **shorts at the near end**, same encoding, symmetric | confirmed |
| 0x140 | 4× u16 | delay of the pairs 12 / 36 / 45 / 78, 4-byte stride | confirmed |
| 0x200 | u8 | **overall result**: 0 = Qualified, 1 = Disqualified, 2 = Information (e.g. no far end) | confirmed |
| 0x204 | u16 | **wiremap faults of the device** as a bit mask (bit 0–7 = wire 1–8, bit 8 = shield) | confirmed |
| 0x206 | n × 28 bytes | **autotest blocks**, one block per autotest performed; the list ends at identifier `0000` (max. 9). Stale data (pattern `06`/`08`) follows and is ignored | confirmed |

### Wiremap encoding (0x114 and 0x12A)

Nine `u16` values for wires 1 to 8 and the shield (index 0 to 8). Each value is a bit mask:

- Bit 0–7 = pin 1–8, bit 8 (0x100) = shield.
- **Far end (0x114):** the mask of wire n names the pins at the far end the wire is connected to. Straight: wire n has `1 << (n-1)`, shield has `0x100`. Open: `0`. Crossed: a different bit position (wire 4 → 5 gives `0x010`). Several bits mean several pins.
- **Shorts (0x12A):** same encoding; the mask names the wires at the near end the wire is shorted with (symmetric: wire 3 ↔ shield carries `0x100` for wire 3 and `0x004` for the shield).
- A shorted wire inherits the pins of the other one in the far-end mask (wire 5 is shorted with wire 3, so wire 5 also carries the pins of wire 3).

### Result and autotests (0x200 ff.)

- **Overall result** (0x200) and **fault mask** (0x204) match the reference values, or the deliberately built faults, in all 22 verified measurements.
- Without a detected far end (remote ID 0 or 0xFF, no wire with a far end) the device does not report a wiremap fault for "open" wires; only real faults such as shorts appear in the mask. The client shows this as "No far end".
- **Autotest block** (28 bytes, from 0x206 at a stride of 28):

| Offset in block | Content |
|---|---|
| 0–1 | u16 identifier (e.g. `1F`, `13`, `09`, `06`; 0 ends the list). Bits 0–3 are a **bit mask of the wire pairs** the test uses (1-2, 3-6, 4-5, 7-8), see below; bit 4 (`0x10`) and bit 8 (`0x100`) are set in some measurements and not understood |
| 2 | **result**: 0 = passed, 1 = failed, 2 = not determinable/information |
| 3 | wiremap result (0 = ok, 1 = fault, 2 = not determinable) |
| 4 | length result (same values) |
| 5 | signal result (1 = **impedance error**, 2 = not determinable, 3 = not applicable) |
| 18–19 | delay of the deciding pair (raw value 1/8 ns) |

- **Mapping of blocks to autotests:** the order is fixed: 1000BASE-T, 100BASE-TX, 10BASE-T, Voice Over IP, Wiremap only, 1394b S100, Telco. Which of them were active in the device follows from the number of blocks: 4 blocks = 1000BASE-T, 100BASE-TX, Voice Over IP, Wiremap only; 6 blocks = additionally 10BASE-T and Telco; 7 blocks = additionally 1394b S100. This mapping is backed by all 22 reference measurements (4, 6 and 7 blocks). Other block counts have not been seen yet; see the identifier mask below for how the client names them.
- **Identifier = pair mask:** `0F` (all four pairs) for 1000BASE-T and Wiremap only, `03` (pairs 1-2 and 3-6) for 100BASE-TX, 10BASE-T and Voice over IP, `09` (pairs 1-2 and 7-8) for 1394b S100 and `06` (pairs 3-6 and 4-5) for Telco. This holds for all 22 measurements; the mask therefore confirms the assignment above but cannot name a test on its own, because several tests share a mask. For block counts not seen so far, the client assigns names only if exactly one assignment in the fixed order fits the masks (for example `09`, `06` = 1394b S100, Telco) and otherwise shows "Autotest N". Bit 4 (`0x10`) is set for some tests of some measurements only (`1F`/`13` instead of `0F`/`03`), bit 8 (`0x100`) in one measurement with a shield fault; their meaning is open.
- The list of qualified tests is the set of all blocks with result byte 0 (identical in 22 of 22 measurements). The detail view of "Gebäude Büro 1" (7 autotests, impedance error for 1000BASE-T, 100BASE-TX, Voice Over IP and 1394b S100) matches the reference values exactly.
- **Reasons** (checked against reference values on Büro 1 and on Los 1 and Los 5): block byte 3 = 1 → "Wiremap", byte 4 = 1 → "Length (termination error)", byte 5 = 1 → "Impedance error", several joined with "; ". Values 2 and 3 produce no reason. **Limitation:** "Length (termination error)" is named only for the four-pair tests (1000BASE-T, Wiremap only), although the length byte is also set in the blocks of 100BASE-TX and Voice Over IP in Los 1. This rule rests on two measurements; the actual mechanism is not understood.
- **Operator fields "Tested by":** two text fields of 38 bytes each at 0x3A and 0x60 (Latin-1, NUL-terminated). Older records contain the placeholder `=`; unsanitised memory content follows it (previously mistaken for measurement data). The client shows the fields, lets you change them per measurement (stored locally only, never written to the device) and uses them as "Tested by" in the PDF.

### Length formula

```
length [m] = delay × 0.3 × 0.70 / 8      (unit 1/8 ns, NVP 70 %)
```

The record stores the delay as a raw value in units of 1/8 ns (one unit = 125 ps). The client converts it to nanoseconds for display (`raw / 8`, three decimals, e.g. 1081 → 135.125 ns).

Checked against reference values for "Gebäude 10 8" (604/615/608/620 → 15.9/16.1/16.0/16.3 m) and "Gebäude Büro 1" (1081/1058/1056/1075 → 28.4/27.8/27.7/28.2 m). The length is not stored in the record; it is computed from the delay. On longer runs the last decimal can differ (e.g. 61.7 instead of 61.8 m); the rounding is not reproduced exactly. The NVP value (70 %) is derived from the reference values.

## 6. Decoded measurements of the capture

All 15 records carry the same serial number and version V1.80.00. Some entries (e.g. no. 9 and 13) have one pair with a strongly deviating delay; this probably means unconnected or faulty pairs and is not interpreted yet.

### Wiremap test measurements (remote ID 1, self-made)

| Cable ID | Setup | Decoded |
|---|---|---|
| Los AA | all wires open | all wires `open` |
| Los AAA | wire 3 shorted to shield | wire 3 ↔ shield in the short field, far end open |
| Los 1 | wires 3 and 7 not connected at the far end | 3 and 7 `open`, rest ok |
| Los 2 | 7 open, 4 and 5 crossed | 4 → 5, 5 → 4, 7 open |
| Los 3 | 3 and 4 open, 7 crossed onto 4 | 3 and 4 open, 7 → 4 |
| Los 4 | 7 and 5 open at the far end, 3 and 5 shorted locally, 3 → 3 and 4 at the far end, 4 → 5 at the far end | 3 → 3,4 (short with 5), 4 → 5, 5 → 3,4 (short with 3), 7 open |
| Los 5 | like Los 4, shield disconnected | like Los 4, shield open |

All setups matched the decoding.

## 7. Open points

- **Reasons:** the mechanism behind "Length (termination error)" (see the limitation above) and the reasons for "Information".
- Block counts other than 4, 6 and 7 (a different autotest selection on the device) and the exact meaning of the identifier (bytes 0–1) and the remaining block fields.
- The rule behind 0x100 (length according to the device), the meaning of 0x102, 0x10E and 0x0C4.
- The meaning of command `06` (response `0x000A`) remains unclear. Whether reading is refused without a preceding lock has not been tested.
- Reproduce the length rounding.

## 8. Method and files

Files of the project (overview and usage: see [README.md](../README.md)):

| File | Purpose |
|---|---|
| `cableiq.py` | protocol library and command-line client (pyusb, read-only): `list`, `show N [--hex]`, `dump DIR`, `diff A B`, `save FILE`; `--pcap` works offline against a capture, `--set` against a saved set, `--lang de|en` selects the language |
| `cableiq_gui.py`, `cableiq_pdf.py` | graphical client (German/English, light/dark) and PDF test report |
| `cableiq_i18n.py` | translation table and number/date formats |
| `cableiq_store.py` | save/load measurement sets (see section 9) |
| `tests/` | regression tests: decoding against reference values, measurement-set format, translations (`python3 -m unittest discover -s tests`) |
| `udev/70-cableiq.rules` | access rights without root |
| `tools/usbcap.py` | reads `/dev/usbmonN` directly (read access is enough) and writes a pcap file |
| `tools/frames.py` | reassembles frames and removes the escaping |

Method: capture the USB traffic with usbmon → split frames → determine fields through targeted test measurements (open, shorted, crossed) and differential analysis of the raw bytes → cross-check with our own client on the real device.

## 9. Measurement-set file format

JSON, UTF-8, `format` = `cableiq-messsatz`, `version` = 1 (newer versions are rejected):

```json
{
 "format": "cableiq-messsatz", "version": 1, "saved": "2026-10-16T17:25:37",
 "device": {"serial": "1234567", "vid": 3966, "pid": 3},
 "records": [
  {"raw": "<base64 of the 768-byte record>", "name": "Los 1 #", "time": "2026-10-16 18:12:13",
   "operators": ["Example Corp", "Netzwerk-Team"]}
 ],
 "protocol": {"location": "…", "tester": "…", "logo": {"name": "logo.png", "data": "<base64>"}}
}
```

- **`raw` is authoritative.** All values (length, wiremap, result, autotests, reasons) are recomputed from the raw data on load; `name` and `time` are only there for orientation when reading the file. Later improvements of the decoding therefore apply to old files as well.
- `operators` is only present if the "Tested by" lines differ from the device values.
- `note` (text) is only present if a note was entered for the measurement.
- `protocol` is optional (location, default for the tester, logo up to 5 MB). The GUI asks before replacing the current details on load.
- The file is written atomically. On load, format, version, base64 and the length of every record (768 bytes) are checked; errors lead to a message, never to half-loaded data.
