"""Wiremap drawing and PDF test report for CableIQ measurements (PySide6)."""
import datetime
import html
import math

from PySide6.QtCore import QMarginsF, QPointF, QRectF, QSizeF, Qt, QUrl
from PySide6.QtGui import (QColor, QFont, QGuiApplication, QImage, QPageLayout, QPageSize, QPainter, QPainterPath, QPdfWriter, QPen,
                           QTextDocument)

from cableiq_i18n import dt, nf, reason_text, tr, wire_text

PAIRS = ["1-2", "3-6", "4-5", "7-8"]  # order as in the record (pair 12/36/45/78)
# color schemes for the wiremap drawing: paper (PDF) and dark interface
LIGHT = {"ok": "#1b8a3a", "bad": "#c62828", "grey": "#888888", "text": "#333333", "dim": "#555555", "bg": "#ffffff"}
DARK = {"ok": "#5fd37f", "bad": "#ff7b72", "grey": "#9aa0a6", "text": "#e6e6e6", "dim": "#b0b0b0", "bg": "#1e1e1e"}
# colors for text in the interface and the PDF (the PDF is always light)
TEXT_COLORS = {False: {"ok": "#1b8a3a", "bad": "#c62828", "neutral": "#666666"},
               True: {"ok": "#5fd37f", "bad": "#ff7b72", "neutral": "#9aa0a6"}}


def hint():
    return tr("This report reproduces the data stored in the tester (result, autotests, length, delay, wiremap, remote ID).")


def result_kind(result):
    """'ok' | 'bad' | 'neutral' for an overall result (English key from Record.result)."""
    return {"Qualified": "ok", "Disqualified": "bad"}.get(result, "neutral")


def draw_wiremap(p: QPainter, r: QRectF, rec, colors=None):
    """Draws the wiremap of rec into the rectangle r; `colors` = LIGHT (default) or DARK."""
    c = {k: QColor(v) for k, v in (colors or LIGHT).items()}
    wires = rec.wires
    n = len(wires)
    gap = r.height() * 0.03  # gap before the shield
    row = (r.height() - gap - 30) / (n - 1) if n > 1 else 0
    y0 = r.top() + 24
    xl, xr = r.left() + r.width() * 0.34, r.right() - r.width() * 0.34

    def y(i):
        return y0 + i * row + (gap if i == n - 1 else 0)

    f = QFont(p.font())
    f.setPixelSize(min(15, max(9, int(row * 0.48))))
    p.setFont(f)
    p.setPen(c["dim"])
    p.drawText(QRectF(xl - 40, r.top(), 80, 16), Qt.AlignHCenter | Qt.AlignVCenter, tr("Near"))
    p.drawText(QRectF(xr - 40, r.top(), 80, 16), Qt.AlignHCenter | Qt.AlignVCenter, tr("Far"))
    for i, w in enumerate(wires):
        yy = y(i)
        p.setPen(c["text"])
        p.drawText(QRectF(xl - 26, yy - row / 2, 20, row), Qt.AlignRight | Qt.AlignVCenter, w["name"])
        p.drawText(QRectF(xr + 6, yy - row / 2, 20, row), Qt.AlignLeft | Qt.AlignVCenter, w["name"])
        p.setBrush(c["text"])
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(xl, yy), 2.2, 2.2)
        p.drawEllipse(QPointF(xr, yy), 2.2, 2.2)
        p.setBrush(Qt.NoBrush)
        if w["state"] == "open":
            p.setPen(QPen(c["grey"], 1.2, Qt.DashLine))
            xm = xl + (xr - xl) * 0.35
            p.drawLine(QPointF(xl, yy), QPointF(xm, yy))
            p.setPen(QPen(c["bad"], 1.6))
            p.drawLine(QPointF(xm - 3, yy - 3), QPointF(xm + 3, yy + 3))
            p.drawLine(QPointF(xm - 3, yy + 3), QPointF(xm + 3, yy - 3))
        for pin in w["far"]:
            j = n - 1 if pin == "S" else int(pin) - 1
            p.setPen(QPen(c["ok"] if j == i else c["bad"], 1.6))
            p.drawLine(QPointF(xl, yy), QPointF(xr, y(j)))
    # short circuits at the near end: bracket on the left
    p.setPen(QPen(c["bad"], 1.6))
    seen = set()
    for i, w in enumerate(wires):
        for pin in w["shorts"]:
            j = n - 1 if pin == "S" else int(pin) - 1
            key = (min(i, j), max(i, j))
            if key in seen:
                continue
            seen.add(key)
            off = 6 + 6 * (len(seen) - 1)
            path = QPainterPath(QPointF(xl - 30, y(key[0])))
            path.lineTo(xl - 30 - off, y(key[0]))
            path.lineTo(xl - 30 - off, y(key[1]))
            path.lineTo(xl - 30, y(key[1]))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)


def wiremap_image(rec, width=300, height=330, scale=2):
    img = QImage(width * scale, height * scale, QImage.Format_RGB32)
    img.fill(Qt.white)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(scale, scale)
    draw_wiremap(p, QRectF(8, 4, width - 16, height - 8), rec, LIGHT)
    p.end()
    return img


def fault_summary(rec, with_shield=True):
    """Short description of the wiremap deviations (empty if everything is fine)."""
    out, seen = [], set()
    names = rec.WIRE_NAMES
    for w in rec.wires[:8]:
        if w["state"] == "open":
            out.append(tr("Wire {n} open").format(n=w["name"]))
        elif w["state"] == "wrong":
            out.append(tr("Wire {n} on pin {p}").format(n=w["name"], p=", ".join(w["far"])))
        for o in w["shorts"]:
            key = tuple(sorted((w["name"], o), key=names.index))
            if key not in seen:
                seen.add(key)
                out.append(tr("Short wire {a}–{b}").format(a=key[0], b=key[1]))
    if with_shield and not rec.shield_ok:
        sh = rec.wires[8]
        out.append(tr("Shield disconnected") if sh["state"] == "open"
                   else tr("Shield: {t}").format(t=wire_text(sh)))
    return out


def wiremap_status(rec):
    """(short text, ok) for lists and the report; ok=None if no far end was detected."""
    if rec.no_remote and rec.wiremap_ok:
        return tr("No far end"), None
    if rec.wiremap_ok:
        return (tr("All OK") if rec.shield_ok else tr("All OK (shield disconnected)")), True
    return tr("Error"), False


def remote_label(rec):
    return tr("none") if rec.remote_text == "none" else rec.remote_text


def _e(s):
    return html.escape(str(s))


def _cls(kind):
    return TEXT_COLORS[False][kind]


# design of the PDF (paper, always light)
ACCENT = "#1f3a5f"     # header area, table heads, headings
LINE = "#d0d5dd"       # table lines
ZEBRA = "#f3f5f8"      # every second table row
LABEL = "#667085"      # labels
BANNER = {"ok": "#1b8a3a", "bad": "#c62828", "neutral": "#667085"}


def _header(ctx, person=None):
    logo = f'<img src="logo" height="{ctx["logo_h"]}">' if ctx["logo"] else ""
    loc = _e(ctx["location"]) or "–"
    sub = f"{_e(tr("Location:"))} {loc}"
    if person is not None:
        sub += f"<br>{_e(tr("Tested by:"))} {_e(person) or "–"}"
    return f"""
<table width="100%" cellspacing="0" cellpadding="0"><tr>
 <td width="40%" valign="middle">{logo}</td>
 <td width="60%" align="right" valign="middle">
  <span style="font-size:17pt; font-weight:bold; color:{ACCENT};">{_e(tr("Cable test report"))}</span><br>
  <span style="font-size:9pt; color:{LABEL};">{sub}</span></td>
</tr></table>
<table width="100%" cellspacing="0" cellpadding="0" style="margin-top:6px;"><tr>
 <td bgcolor="{ACCENT}" style="font-size:3pt;">&nbsp;</td></tr></table>
"""


def _section(title):
    return (f'<p style="margin-top:12px; margin-bottom:3px; font-size:10.5pt; font-weight:bold; '
            f'color:{ACCENT};">{_e(title)}</p>')


def _table(head, rows, widths, aligns=None):
    """Table with a colored head and alternately tinted rows; rows = list of lists of cell HTML."""
    aligns = aligns or ["left"] * len(head)
    th = "".join(f'<th align="{a}" width="{w}%" bgcolor="{ACCENT}" style="color:#ffffff;">{_e(h)}</th>'
                 for h, w, a in zip(head, widths, aligns))
    body = ""
    for n, cells in enumerate(rows):
        bg = ZEBRA if n % 2 else "#ffffff"
        body += "<tr>" + "".join(f'<td align="{a}" bgcolor="{bg}">{c}</td>' for c, a in zip(cells, aligns)) + "</tr>"
    return (f'<table width="100%" cellspacing="0" cellpadding="3" border="1" style="border-color:{LINE};">'
            f'<tr>{th}</tr>{body}</table><p style="font-size:7pt; margin:0;">&nbsp;</p>')


def _notes(text):
    """Notes box: filled with the text, otherwise an empty box for handwriting."""
    inner = _e(text).replace("\n", "<br>") if text else "&nbsp;<br>&nbsp;<br>&nbsp;<br>&nbsp;"
    return (_section(tr("Notes"))
            + f'<table width="97%" cellspacing="0" cellpadding="6" border="1" style="border-color:{LINE};">'
              f'<tr><td>{inner}</td></tr></table><p style="font-size:7pt; margin:0;">&nbsp;</p>')


def _signature():
    cell = (f'<td width="45%" style="border-top:1px solid #333333; color:{LABEL}; font-size:8pt;">')
    return (_section(tr("Confirmation"))
            + '<p style="margin:0;">&nbsp;<br>&nbsp;<br>&nbsp;</p>'
              '<table width="100%" cellspacing="0" cellpadding="2"><tr>'
              f'{cell}{_e(tr("Place, date"))}</td><td width="10%">&nbsp;</td>'
              f'{cell}{_e(tr("Signature"))}</td></tr></table>')


def _page(rec, serial, idx, total, ctx, first, person="", note="", signature=False):
    st, ok = wiremap_status(rec)
    col = _cls({True: "ok", False: "bad", None: "neutral"}[ok])
    kind = result_kind(rec.result)
    okc, badc = _cls("ok"), _cls("bad")
    tests = [[_e(tr(t["name"])),
              f"<span style='color:{okc if t["qualified"] else badc}'><b>"
              f"{_e(tr("Qualified") if t["qualified"] else tr("Disqualified"))}</b></span>",
              _e(reason_text(t["reason"])) or "–"] for t in rec.autotests]
    pb = "" if first else ' style="page-break-before: always;"'
    faults = fault_summary(rec)
    rows = [[_e(w["name"]), _e(wire_text(w)),
             f"<span style='color:{badc if w["fault"] else okc}'><b>"
             f"{_e(tr("Error") if w["fault"] else tr("OK"))}</b></span>"] for w in rec.wires]
    lens = [[_e(tr("Pair {p}").format(p=PAIRS[i])), f"{nf(rec.lengths[i], 1)} m", f"{nf(rec.delays_ns[i], 3)} ns"]
            for i in range(4)]
    return f"""
<div{pb}>{_header(ctx, person)}</div>
<table width="100%" cellspacing="0" cellpadding="8" style="margin-top:10px;"><tr>
 <td width="62%" bgcolor="{BANNER[kind]}" valign="middle">
  <span style="font-size:17pt; font-weight:bold; color:#ffffff;">{_e(rec.name)}</span><br>
  <span style="font-size:9pt; color:#ffffff;">{dt(rec.time)}</span></td>
 <td width="38%" bgcolor="{BANNER[kind]}" align="right" valign="middle">
  <span style="font-size:8pt; color:#ffffff;">{_e(tr("Result:").rstrip(":").upper())}</span><br>
  <span style="font-size:15pt; font-weight:bold; color:#ffffff;">{_e(tr(rec.result)).upper()}</span></td>
</tr></table>
<table width="100%" cellspacing="0" cellpadding="4" style="margin-top:6px;">
 <tr><td width="18%" style="color:{LABEL};">{_e(tr("Wiremap"))}</td>
     <td width="32%"><b style="color:{col};">{_e(st)}</b></td>
     <td width="18%" style="color:{LABEL};">{_e(tr("Remote ID"))}</td><td width="32%">{_e(remote_label(rec))}</td></tr>
 <tr><td style="color:{LABEL};">{_e(tr("Device"))}</td><td>{_e(tr("Fluke CableIQ, no. {s}").format(s=serial))}</td>
     <td style="color:{LABEL};">{_e(tr("Firmware"))}</td><td>{_e(rec.version)}</td></tr>
</table>
{('<p style="color:' + badc + '; margin-top:2px;"><b>' + _e("; ".join(faults)) + "</b></p>") if faults else ""}
{_section(tr("Autotests"))}
{_table([tr("Autotest"), tr("Result"), tr("Reason")], tests, [32, 24, 44])}
<table width="100%" cellspacing="0" cellpadding="0"><tr>
 <td width="52%" valign="top">
  {_section(tr("Length and delay per wire pair"))}
  {_table([tr("Pair"), tr("Length"), tr("Delay")], lens, [34, 33, 33], ["left", "right", "right"])}
  {_section(tr("Wires"))}
  {_table([tr("Wire"), tr("Far end"), tr("Status")], rows, [18, 56, 26])}
 </td>
 <td width="4%">&nbsp;</td>
 <td width="44%" align="center" valign="top">{_section(tr("Wiremap"))}
  <img src="wm{idx}" width="270">
  <div align="left">{_notes(note)}</div></td>
</tr></table>
{_signature() if signature else ""}
"""


def _overview(recs, ctx, signature=False):
    rows = [[str(i + 1), _e(r.name), dt(r.time, False), f"{nf(max(r.lengths), 1)} m",
             f"<span style='color:{_cls(result_kind(r.result))}'><b>{_e(tr(r.result))}</b></span>",
             _e("; ".join(tr(n) for n in r.qualified_names)) or "–"]
            for i, r in enumerate(recs)]
    return f"""
{_header(ctx)}
<p style="font-size:13pt; font-weight:bold; color:{ACCENT}; margin-top:12px;">{_e(tr("Overview ({n} measurements)").format(n=len(recs)))}</p>
{_table(["#", tr("Cable ID"), tr("Date"), tr("Length*"), tr("Result"), tr("Qualified")], rows,
        [5, 22, 17, 12, 18, 26], ["right", "left", "left", "right", "left", "left"])}
<p style="color:{LABEL}; font-size:8pt;">{_e(tr("* longest wire pair"))}</p>
{_signature() if signature else ""}
"""


def _footer(p, rect, serial, page, pages, ctx):
    """Footer: line, note, below it device/creation date on the left and the page number on the right."""
    f = QFont("Sans Serif")
    f.setPixelSize(max(8, int(rect.height() * 0.3)))
    p.setFont(f)
    p.setPen(QPen(QColor(LINE), 1))
    p.drawLine(QPointF(rect.left(), rect.top()), QPointF(rect.right(), rect.top()))
    p.setPen(QColor(LABEL))
    half = rect.height() / 2
    r1 = QRectF(rect.left(), rect.top() + 2, rect.width(), half - 2)
    r2 = QRectF(rect.left(), rect.top() + half, rect.width(), half)
    p.drawText(r1, Qt.AlignLeft | Qt.AlignVCenter, hint())
    p.drawText(r2, Qt.AlignLeft | Qt.AlignVCenter,
               f"{tr("Fluke CableIQ, no. {s}").format(s=serial)}  ·  "
               f"{tr("created {d}").format(d=dt(ctx["now"], False))}")
    p.drawText(r2, Qt.AlignRight | Qt.AlignVCenter, tr("Page {p} of {n}").format(p=page, n=pages))


def export_pdf(path, recs, serial, location="", tester="", logo_path="", people=None, notes=None, signature=False):
    """Writes a PDF with one page per measurement (preceded by an overview if there are several).

    people: list of the persons who tested, per measurement; empty entries (or None) fall back to `tester`.
    notes: list of the notes per measurement (empty = empty notes box for handwriting).
    signature: signature field (place, date, signature) on every page.
    Language and number format follow cableiq_i18n; the PDF is always light (paper).
    """
    doc = QTextDocument()
    doc.setDefaultFont(QFont("Sans Serif", 9))
    doc.setDocumentMargin(0)
    # paper is always light: do not take the text color from the (possibly dark) application palette
    doc.setDefaultStyleSheet("body, p, td, th { color: #1a1a1a; }")
    logo = QImage(logo_path) if logo_path else QImage()
    has_logo = not logo.isNull()
    if has_logo:
        logo = logo.scaledToHeight(min(logo.height(), 240), Qt.SmoothTransformation)
        doc.addResource(QTextDocument.ImageResource, QUrl("logo"), logo)
    ctx = {"location": location, "tester": tester, "logo": has_logo, "logo_h": 52,
           "now": datetime.datetime.now()}
    for i, r in enumerate(recs):
        doc.addResource(QTextDocument.ImageResource, QUrl(f"wm{i}"), wiremap_image(r))
    body = ""
    if len(recs) > 1:
        body += _overview(recs, ctx, signature)
    for i, r in enumerate(recs):
        person = (people[i] if people and i < len(people) else "") or tester
        note = (notes[i] if notes and i < len(notes) else "") or ""
        body += _page(r, serial, i, len(recs), ctx, first=(i == 0 and len(recs) == 1), person=person,
                      note=note.strip(), signature=signature)
    doc.setHtml(f"<html><body style='font-family:Sans Serif;'>{body}</body></html>")
    w = QPdfWriter(path)
    w.setPageSize(QPageSize(QPageSize.A4))
    w.setPageMargins(QMarginsF(15, 15, 15, 15), QPageLayout.Millimeter)
    w.setTitle(tr("Cable test report"))
    w.setCreator("cableiq_gui")
    # output the pages ourselves (instead of doc.print_) so that a footer with page numbers is possible
    area = w.pageLayout().paintRectPixels(w.resolution())
    scale = w.logicalDpiX() / QGuiApplication.primaryScreen().logicalDotsPerInchX()
    foot = 34 * scale
    page_w, page_h = area.width() / scale - 2, (area.height() - foot) / scale
    doc.setPageSize(QSizeF(page_w, page_h))
    pages = max(1, math.ceil(doc.size().height() / page_h - 0.02))   # avoid an empty trailing page caused by rounding
    p = QPainter(w)
    for n in range(pages):
        if n:
            w.newPage()
        p.save()
        p.scale(scale, scale)
        p.translate(0, -n * page_h)
        doc.drawContents(p, QRectF(0, n * page_h, page_w, page_h))
        p.restore()
        _footer(p, QRectF(0, area.height() - foot + 6 * scale, area.width(), foot - 6 * scale), serial, n + 1,
                pages, ctx)
    p.end()
