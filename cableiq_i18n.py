"""Language selection (German/English) as well as number and date formats.

English is the base language: the English text is the key, tr("Qualified") returns "Qualifiziert" in German.
Texts with placeholders are formatted with named fields: tr("Measurement {n}").format(n=1).
A test (tests/test_i18n.py) makes sure that every key used in the code has a German translation.
"""
import os

LANGS = {"de": "Deutsch", "en": "English"}
_lang = "en"


def detect():
    """Determine the language from the environment (CABLEIQ_LANG, LC_ALL, LC_MESSAGES, LANG); English otherwise."""
    for var in ("CABLEIQ_LANG", "LC_ALL", "LC_MESSAGES", "LANG"):
        v = os.environ.get(var, "")
        if v and v not in ("C", "POSIX"):
            return "de" if v.lower().startswith("de") else "en"
    return "en"


def set_lang(code):
    """'de', 'en' or 'auto'. Returns the chosen language."""
    global _lang
    _lang = detect() if code in (None, "", "auto") else (code if code in LANGS else "en")
    return _lang


def lang():
    return _lang


def tr(s):
    return DE.get(s, s) if _lang == "de" else s


def nf(x, nd=1):
    """Number with decimal comma (de) or point (en)."""
    s = f"{x:.{nd}f}"
    return s.replace(".", ",") if _lang == "de" else s


def dt(d, seconds=True):
    """Date and time: de 16.10.2026 18:12:13, en 2026-10-16 18:12:13."""
    if _lang == "de":
        return d.strftime("%d.%m.%Y %H:%M:%S" if seconds else "%d.%m.%Y %H:%M")
    return d.strftime("%Y-%m-%d %H:%M:%S" if seconds else "%Y-%m-%d %H:%M")


def wire_text(w):
    """Text for a wire from Record.wires: ok / open / -> pins, with short circuit if any."""
    if w["state"] == "ok":
        t = tr("ok")
    elif w["state"] == "open":
        t = tr("open")
    else:
        t = "→ " + ",".join(w["far"])
    if w["shorts"]:
        t += "  " + tr("short with") + " " + ",".join(w["shorts"])
    return t


def reason_text(s):
    """Translate the reason(s) of an autotest (parts separated by '; ')."""
    return "; ".join(tr(p) for p in s.split("; ") if p)


# Translation table English -> German. Key = English text (see tr()).
DE = {
    # --- command line
    "Fluke Networks CableIQ: read stored measurements (read-only).":
        "Fluke Networks CableIQ: gespeicherte Messungen lesen (nur lesend).",
    "output language (default: from the environment)": "Sprache der Ausgabe (Standard: aus der Umgebung)",
    "use a capture instead of the device": "Mitschnitt statt Gerät verwenden",
    "use a saved measurement set (JSON) instead of the device": "gespeicherten Messsatz (JSON) statt Gerät verwenden",
    "list measurements": "Messungen auflisten",
    "write raw records as .bin/.hex": "Rohdatensätze als .bin/.hex ablegen",
    "save measurements as a set (JSON); load later with --set":
        "Messungen als Messsatz (JSON) speichern; später mit --set laden",
    "show one measurement (1 = newest)": "eine Messung anzeigen (1 = neueste)",
    "byte differences between two records": "Byte-Unterschiede zweier Datensätze",
    "CableIQ not found (check the USB connection; is the device in use by another program or a VM?)":
        "CableIQ nicht gefunden (USB-Verbindung prüfen; wird das Gerät von einem anderen Programm oder einer VM verwendet?)",
    "Warning: device reports {a}, received {b}": "Warnung: Gerät meldet {a}, empfangen {b}",
    "Serial number {s}, {n} measurements": "Seriennummer {s}, {n} Messungen",
    "Cable ID": "Kabel-ID",
    "Date/time": "Datum/Uhrzeit",
    "Length 12/36/45/78 (m)": "Länge 12/36/45/78 (m)",
    "Version": "Version",
    "Record {n} does not exist (1..{m})": "Datensatz {n} existiert nicht (1..{m})",
    "{n} measurements saved to {f}": "{n} Messungen in {f} gespeichert",
    "Delay (ns):": "Laufzeit (ns):",
    "Length (m):": "Länge (m):",
    "Result:": "Ergebnis:",
    "Qualified:": "Qualifiziert:",
    "Remote ID:": "Remote-ID:",
    "Wiremap (wire: far end):": "Wiremap (Ader: Gegenstelle):",
    "Warning: record length {n}": "Warnung: Datensatzlänge {n}",
    "Unlock failed: {e}": "Unlock fehlgeschlagen: {e}",
    "{n} records written to {d}": "{n} Datensätze nach {d} geschrieben",
    "Device {s} {v}": "Gerät {s} {v}",
    "{n} of {m} bytes differ": "{n} von {m} Bytes unterschiedlich",
    # --- results, autotests, reasons (also used dynamically)
    "Qualified": "Qualifiziert",
    "Disqualified": "Disqualifiziert",
    "Information": "Informationen",
    "none": "keine",
    "1000BASE-T": "1000BASE-T",
    "100BASE-TX": "100BASE-TX",
    "10BASE-T": "10BASE-T",
    "Voice over IP": "Voice Over IP",
    "1394b S100": "1394b S100",
    "Telco": "Telco",
    "Wiremap only": "Nur Wiremap",
    "Length (termination error)": "Länge (Abschlussfehler)",
    "Impedance error": "Impedanzfehler",
    # --- GUI
    "Name / company": "Name / Firma",
    "Department / extra": "Abteilung / Zusatz",
    "Device value": "Gerätewert",
    "Discard the change and use the value stored in the device":
        "Änderung verwerfen und den im Gerät gespeicherten Wert verwenden",
    "Note: result and autotests come from the data stored in the device.":
        "Hinweis: Ergebnis und Autotests stammen aus den im Gerät gespeicherten Daten.",
    "Length (m)": "Länge (m)",
    "Result": "Ergebnis",
    "Wiremap": "Wiremap",
    "Read from device": "Vom Gerät auslesen",
    "Save measurement set…": "Messsatz speichern…",
    "Load measurement set…": "Messsatz laden…",
    "PDF test report": "PDF-Messprotokoll",
    "Export selected measurements…": "Ausgewählte Messungen exportieren…",
    "Export all measurements…": "Alle Messungen exportieren…",
    "Settings": "Einstellungen",
    "Quit": "Beenden",
    "Report details": "Protokollangaben",
    "e.g. Building B10, server room": "z. B. Gebäude B10, Serverraum",
    "Default if the device has no entry": "Vorgabe, falls das Gerät keine Angabe enthält",
    "Location:": "Standort:",
    "Tested by (default):": "Messende Person (Vorgabe):",
    "Choose logo…": "Logo wählen…",
    "Remove": "Entfernen",
    "Logo:": "Logo:",
    "Language": "Sprache",
    "Appearance": "Darstellung",
    "Choose logo": "Logo wählen",
    "Reading failed": "Auslesen fehlgeschlagen",
    "Longest value of the four wire pairs": "Längster Wert der vier Adernpaare",
    "Save measurement set": "Messsatz speichern",
    "Test report": "Messprotokoll",
    "Save PDF test report": "PDF-Messprotokoll speichern",
    "Wire pair": "Adernpaar",
    "Delay (ns)": "Laufzeit (ns)",
    "Autotest": "Autotest",
    "Reason": "Grund",
    "Wire": "Ader",
    "Far end": "Gegenstelle",
    "Status": "Status",
    "Tested by (changed):": "Getestet durch (geändert):",
    "Tested by:": "Getestet durch:",
    "No measurement selected": "Keine Messung ausgewählt",
    "Automatic": "Automatisch",
    "Automatic (system)": "Automatisch (System)",
    "Light": "Hell",
    "Dark": "Dunkel",
    "The language cannot be changed while reading.": "Sprache kann während des Auslesens nicht gewechselt werden.",
    "Images": "Bilder",
    "Reading measurements …": "Lese Messungen …",
    "cableiq-measurements-{s}-{d}.json": "cableiq-messungen-{s}-{d}.json",
    "CableIQ measurement set": "CableIQ-Messsatz",
    "Load measurement set": "Messsatz laden",
    "{n} measurements loaded from {f}": "{n} Messungen aus {f} geladen",
    "Replace the current details?": "Die aktuellen Angaben ersetzen?",
    "Logo": "Logo",
    "{d} · Remote ID: {r} · Device no. {s}, firmware {v}": "{d} · Remote-ID: {r} · Gerät Nr. {s}, Firmware {v}",
    "no logo": "kein Logo",
    "File not readable": "Datei nicht lesbar",
    "The file could not be read as an image.": "Die Datei konnte nicht als Bild gelesen werden.",
    "Reading measurement {n} of {t} …": "Lese Messung {n} von {t} …",
    "{n} measurements read from device {s}": "{n} Messungen von Gerät {s} gelesen",
    "Export": "Export",
    "{n} measurement(s) exported to {f}": "{n} Messung(en) nach {f} exportiert",
    "Configuration not saved: {e}": "Konfiguration nicht gespeichert: {e}",
    "No access to the USB device (permissions). Please grant access with a udev rule or `setfacl -m u:$USER:rw /dev/bus/usb/BBB/DDD`.":
        "Kein Zugriff auf das USB-Gerät (Rechte). Bitte per udev-Regel oder `setfacl -m u:$USER:rw /dev/bus/usb/BBB/DDD` freigeben.",
    "Length and delay per wire pair": "Länge und Laufzeit je Adernpaar",
    "Autotests": "Autotests",
    "Wires": "Adern",
    "Wiremap:": "Wiremap:",
    "Pair {p}": "Paar {p}",
    "Error": "Fehler",
    "OK": "OK",
    "Loading {f} …": "Lade {f} …",
    "(saved {d})": "(gespeichert {d})",
    "The logo {f} is not readable and will be omitted.": "Das Logo {f} ist nicht lesbar und wird weggelassen.",
    "The PDF could not be written:": "PDF konnte nicht geschrieben werden:",
    "The device does not respond. Please switch it off and on or replug it.":
        "Das Gerät antwortet nicht. Bitte aus- und wieder einschalten bzw. neu anstecken.",
    "The measurement set contains report details:": "Der Messsatz enthält Protokollangaben:",
    "The logo could not be saved: {e}": "Logo konnte nicht gespeichert werden: {e}",
    "USB error: {e}": "USB-Fehler: {e}",
    # --- wiremap, PDF
    "ok": "ok",
    "open": "offen",
    "short with": "Kurzschluss mit",
    "This report reproduces the data stored in the tester (result, autotests, length, delay, wiremap, remote ID).":
        "Dieses Protokoll gibt die im Messgerät gespeicherten Daten wieder (Ergebnis, Autotests, Länge, Laufzeit, Wiremap, Remote-ID).",
    "Near": "Nah",
    "Far": "Fern",
    "Cable test report": "Messprotokoll Kabeltest",
    "No far end": "Keine Gegenstelle",
    "Shield disconnected": "Schirm getrennt",
    "All OK": "In Ordnung",
    "All OK (shield disconnected)": "In Ordnung (Schirm getrennt)",
    "Remote ID": "Remote-ID",
    "Device": "Messgerät",
    "Firmware": "Firmware",
    "Pair": "Paar",
    "Length": "Länge",
    "Delay": "Laufzeit",
    "Date": "Datum",
    "Length*": "Länge*",
    "* longest wire pair": "* längstes Adernpaar",
    "Wire {n} open": "Ader {n} offen",
    "Shield: {t}": "Schirm: {t}",
    "Fluke CableIQ, no. {s}": "Fluke CableIQ, Nr. {s}",
    "Page {p} of {n}": "Seite {p} von {n}",
    "Notes": "Notizen",
    "Confirmation": "Bestätigung",
    "Place, date": "Ort, Datum",
    "Signature": "Unterschrift",
    "Notes on this measurement:": "Notizen zur Messung:",
    "Remarks on this measurement (shown in the PDF)": "Anmerkungen zu dieser Messung (erscheinen im PDF)",
    "Signature field in PDF:": "Unterschriftsfeld im PDF:",
    "Add signature field (place, date, signature)": "Unterschriftsfeld (Ort, Datum, Unterschrift) einfügen",
    "Overview ({n} measurements)": "Übersicht ({n} Messungen)",
    "created {d}": "erstellt am {d}",
    "Wire {n} on pin {p}": "Ader {n} auf Pin {p}",
    "Short wire {a}–{b}": "Kurzschluss Ader {a}–{b}",
    # --- measurement-set file
    "ops and recs differ in length": "ops und recs haben unterschiedliche Länge",
    "This is not a CableIQ measurement set.": "Das ist kein CableIQ-Messsatz.",
    "Unknown file version {v} (supported up to {m}).": "Unbekannte Dateiversion {v} (unterstützt bis {m}).",
    "The file could not be written: {e}": "Datei konnte nicht geschrieben werden: {e}",
    "File not readable: {e}": "Datei nicht lesbar: {e}",
    "Measurement set is damaged: {e}": "Messsatz ist beschädigt: {e}",
    "Measurement {i}: record has {n} instead of {m} bytes.": "Messung {i}: Datensatz hat {n} statt {m} Byte.",
    "Measurement {i}: invalid 'operators' entry.": "Messung {i}: ungültige Angabe 'operators'.",
    "Measurement {i}: invalid 'note' entry.": "Messung {i}: ungültige Angabe 'note'.",
}
