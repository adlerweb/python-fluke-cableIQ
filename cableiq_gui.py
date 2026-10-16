#!/usr/bin/env python3
"""CableIQ client: read, view and export measurements as a PDF test report.

  cableiq_gui.py                 read the measurements from the device at start
  cableiq_gui.py --no-auto       start without reading from the device
  cableiq_gui.py --pcap FILE     load from a usbmon capture (no device)
  cableiq_gui.py --set FILE      load a saved measurement set (no device)
  cableiq_gui.py --lang de|en    language for this session

Settings: ~/.config/cableiq/config.json (location, logo, language, appearance ...).
The device must not be used by another program or a VM at the same time.
"""
import argparse
import datetime
import json
import os
import signal
import sys
from pathlib import Path

from PySide6.QtCore import QLibraryInfo, QObject, QRectF, Qt, QThread, QTimer, QTranslator, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QGuiApplication, QKeySequence, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox, QProgressBar,
                               QPlainTextEdit, QPushButton, QSizePolicy, QSplitter, QTableWidget, QTableWidgetItem, QToolBar, QToolButton,
                               QVBoxLayout, QWidget)

import cableiq
import cableiq_i18n as i18n
import cableiq_store
from cableiq_i18n import LANGS, dt, nf, reason_text, tr, wire_text
from cableiq_pdf import (DARK, LIGHT, PAIRS, TEXT_COLORS, draw_wiremap, export_pdf, fault_summary, remote_label,
                         result_kind, wiremap_status)

CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "cableiq" / "config.json"
DEFAULTS = {"location": "", "tester": "", "logo": "", "pdf_dir": "", "set_dir": "", "operators": {}, "notes": {}, "signature": False,
            "lang": "auto", "theme": "auto"}
LANG_OVERRIDE = None   # --lang for this session (not saved)
_WINDOWS = []          # keep the windows alive (rebuilt on a language change)
_QT_TRANSLATORS = []


def load_config():
    try:
        cfg = {**DEFAULTS, **json.loads(CONFIG.read_text("utf-8"))}
    except (OSError, ValueError):
        cfg = dict(DEFAULTS)
    cfg["operators"] = dict(cfg["operators"]) if isinstance(cfg["operators"], dict) else {}
    cfg["notes"] = {k: v for k, v in cfg["notes"].items() if isinstance(v, str)} if isinstance(cfg["notes"], dict) else {}
    cfg["signature"] = bool(cfg["signature"])
    if cfg["lang"] not in ("auto", "de", "en"):
        cfg["lang"] = "auto"
    if cfg["theme"] not in ("auto", "light", "dark"):
        cfg["theme"] = "auto"
    return cfg


def save_config(cfg):
    try:
        CONFIG.parent.mkdir(parents=True, exist_ok=True)
        tmp = CONFIG.with_suffix(".tmp")
        tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), "utf-8")
        tmp.replace(CONFIG)
    except OSError as e:
        print(tr("Configuration not saved: {e}").format(e=e), file=sys.stderr)


_SYSTEM_PALETTE = []   # the platform's palette, before we override it


def is_dark():
    """Dark interface? What counts is the palette actually in use (not every platform reports a color scheme)."""
    return QApplication.palette().color(QPalette.Window).lightness() < 128


def dark_palette():
    p = QPalette()
    roles = {QPalette.Window: "#2b2b2b", QPalette.WindowText: "#e6e6e6", QPalette.Base: "#1e1e1e",
             QPalette.AlternateBase: "#2b2b2b", QPalette.Text: "#e6e6e6", QPalette.Button: "#3a3a3a",
             QPalette.ButtonText: "#e6e6e6", QPalette.ToolTipBase: "#3a3a3a", QPalette.ToolTipText: "#e6e6e6",
             QPalette.PlaceholderText: "#8a8a8a", QPalette.Link: "#4da3ff", QPalette.Highlight: "#2a82da",
             QPalette.HighlightedText: "#ffffff", QPalette.BrightText: "#ffffff"}
    for role, col in roles.items():
        p.setColor(role, QColor(col))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        p.setColor(QPalette.Disabled, role, QColor("#7f7f7f"))
    return p


def apply_theme(theme):
    """theme: auto (platform/system), light or dark. Uses our own palette where the platform does not support it."""
    app = QApplication.instance()
    if not _SYSTEM_PALETTE:
        _SYSTEM_PALETTE.append(app.palette())
    scheme = {"light": Qt.ColorScheme.Light, "dark": Qt.ColorScheme.Dark}.get(theme, Qt.ColorScheme.Unknown)
    QGuiApplication.styleHints().setColorScheme(scheme)  # works if the platform supports it (Qt >= 6.8)
    if theme == "auto":
        app.setPalette(_SYSTEM_PALETTE[0])
    elif theme == "dark":
        if not is_dark():
            app.setStyle("Fusion")
            app.setPalette(dark_palette())
    else:  # light
        if is_dark():
            app.setStyle("Fusion")
            app.setPalette(app.style().standardPalette())


def tc(kind):
    """Text color matching the current appearance; kind = ok | bad | neutral."""
    return TEXT_COLORS[is_dark()][kind]


def install_qt_translators(lang):
    """Qt's own texts (dialog buttons etc.) in the chosen language."""
    app = QApplication.instance()
    for t in _QT_TRANSLATORS:
        app.removeTranslator(t)
    _QT_TRANSLATORS.clear()
    if lang == "en":
        return
    path = QLibraryInfo.path(QLibraryInfo.TranslationsPath)
    t = QTranslator()
    if t.load(f"qtbase_{lang}", path):
        app.installTranslator(t)
        _QT_TRANSLATORS.append(t)


class ReadWorker(QObject):
    """Reads all measurements in a thread of its own (about 1 s per record)."""
    progress = Signal(int, int)
    done = Signal(str, list)
    failed = Signal(str)

    def __init__(self, pcap=None):
        super().__init__()
        self.pcap = pcap

    def run(self):
        import usb.core
        t = None
        try:
            t = cableiq.ReplayTransport(self.pcap) if self.pcap else cableiq.UsbTransport()
            serial, recs = cableiq.read_all(t, progress=self.progress.emit)
            self.done.emit(serial, recs)
        except cableiq.DeviceError as e:
            self.failed.emit(str(e))
        except usb.core.USBError as e:
            if getattr(e, "errno", None) == 13:
                self.failed.emit(tr("No access to the USB device (permissions). Please grant access with a udev rule or `setfacl -m u:$USER:rw /dev/bus/usb/BBB/DDD`."))
            elif isinstance(e, usb.core.USBTimeoutError):
                self.failed.emit(tr("The device does not respond. Please switch it off and on or replug it."))
            else:
                self.failed.emit(tr("USB error: {e}").format(e=e))
        except Exception as e:  # noqa: BLE001 - report to the user interface
            self.failed.emit(f"{type(e).__name__}: {e}")
        finally:
            if t:
                try:
                    t.close()
                except Exception:  # noqa: BLE001
                    pass


class WiremapWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.rec = None
        self.setMinimumSize(250, 300)

    def set_record(self, rec):
        self.rec = rec
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        colors = DARK if is_dark() else LIGHT
        p.fillRect(self.rect(), QColor(colors["bg"]))
        if self.rec:
            h = min(self.height() - 8, 380)
            draw_wiremap(p, QRectF(8, 4, self.width() - 16, h), self.rec, colors)


def make_table(rows, headers):
    t = QTableWidget(rows, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.verticalHeader().hide()
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setSelectionMode(QAbstractItemView.NoSelection)
    return t


class _NoteEdit(QPlainTextEdit):
    focus_out = Signal()

    def focusOutEvent(self, ev):
        super().focusOutEvent(ev)
        self.focus_out.emit()


class Detail(QWidget):
    """Detail view of one measurement."""
    operators_changed = Signal(list)   # new values of the two "Tested by" fields
    operators_reset = Signal()         # back to the value from the device
    note_edited = Signal(str)          # note is being typed (in memory only)
    note_done = Signal()               # note field left (save)

    def __init__(self):
        super().__init__()
        self.title = QLabel()
        f = self.title.font()   # font via QFont: a stylesheet freezes the palette's text color
        f.setPointSize(16)
        f.setBold(True)
        self.title.setFont(f)
        self.info = QLabel()
        self.info.setTextFormat(Qt.RichText)
        self.op1 = QLineEdit()
        self.op2 = QLineEdit()
        self.op1.setPlaceholderText(tr("Name / company"))
        self.op2.setPlaceholderText(tr("Department / extra"))
        self.op_reset = QPushButton(tr("Device value"))
        self.op_reset.setToolTip(tr("Discard the change and use the value stored in the device"))
        self.op_label = QLabel()
        for ed in (self.op1, self.op2):
            ed.setMaxLength(37)
            ed.editingFinished.connect(lambda: self.operators_changed.emit([self.op1.text().strip(),
                                                                            self.op2.text().strip()]))
        self.op_reset.clicked.connect(self.operators_reset.emit)
        ops = QHBoxLayout()
        ops.addWidget(self.op_label)
        ops.addWidget(self.op1, 1)
        ops.addWidget(self.op2, 1)
        ops.addWidget(self.op_reset)
        self.note_edit = _NoteEdit()
        self.note_edit.setPlaceholderText(tr("Remarks on this measurement (shown in the PDF)"))
        self.note_edit.setFixedHeight(56)
        self.note_edit.textChanged.connect(lambda: self.note_edited.emit(self.note_edit.toPlainText()))
        self.note_edit.focus_out.connect(self.note_done.emit)
        self.note_label = QLabel(tr("Notes on this measurement:"))
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.RichText)
        self.lengths = make_table(4, [tr("Wire pair"), tr("Length (m)"), tr("Delay (ns)")])
        self.lengths.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.lengths.verticalHeader().setDefaultSectionSize(26)
        self.lengths.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.lengths.setFixedHeight(self.lengths.horizontalHeader().sizeHint().height() + 4 * 26 + 6)
        self.tests = make_table(0, [tr("Autotest"), tr("Result"), tr("Reason")])
        self.tests.verticalHeader().setDefaultSectionSize(26)
        self.tests.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.tests.horizontalHeader().sectionResized.connect(lambda *_: self.tests.resizeRowsToContents())
        self.wires = make_table(9, [tr("Wire"), tr("Far end"), tr("Status")])
        self.wires.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.wiremap = WiremapWidget()
        self.note = QLabel(tr("Note: result and autotests come from the data stored in the device."))
        self.note.setWordWrap(True)

        left = QVBoxLayout()
        left.addWidget(QLabel("<b>" + tr("Length and delay per wire pair") + "</b>"))
        left.addWidget(self.lengths)
        left.addWidget(QLabel("<b>" + tr("Autotests") + "</b>"))
        left.addWidget(self.tests, 1)
        right = QVBoxLayout()
        right.addWidget(QLabel("<b>" + tr("Wiremap") + "</b>"))
        right.addWidget(self.wiremap, 3)
        right.addWidget(QLabel("<b>" + tr("Wires") + "</b>"))
        right.addWidget(self.wires, 2)
        cols = QHBoxLayout()
        cols.addLayout(left, 1)
        cols.addLayout(right, 1)
        lay = QVBoxLayout(self)
        for w in (self.title, self.info):
            lay.addWidget(w)
        lay.addLayout(ops)
        lay.addWidget(self.note_label)
        lay.addWidget(self.note_edit)
        lay.addWidget(self.status)
        lay.addLayout(cols, 1)
        lay.addWidget(self.note)
        self.show_record(None, "")

    def set_note(self, text, enabled):
        self.note_edit.blockSignals(True)
        self.note_edit.setPlainText(text)
        self.note_edit.blockSignals(False)
        self.note_edit.setEnabled(enabled)

    def set_operators(self, lines, overridden, enabled):
        for ed, t in zip((self.op1, self.op2), lines):
            ed.blockSignals(True)
            ed.setText(t)
            ed.blockSignals(False)
            ed.setEnabled(enabled)
        self.op_reset.setEnabled(enabled and overridden)
        self.op_label.setText(tr("Tested by (changed):") if overridden else tr("Tested by:"))

    def show_record(self, rec, serial, ops=None, overridden=False, note=""):
        self.wiremap.set_record(rec)
        self.set_note(note, rec is not None)
        self.note.setStyleSheet(f"color: {tc("neutral")};")
        self.set_operators(ops or ["", ""], overridden, rec is not None)
        self.tests.setRowCount(0)
        for t in (self.lengths, self.wires):
            for r in range(t.rowCount()):
                for c in range(t.columnCount()):
                    t.setItem(r, c, QTableWidgetItem(""))
        if rec is None:
            self.title.setText(tr("No measurement selected"))
            self.info.setText("")
            self.status.setText("")
            return
        self.title.setText(rec.name)
        self.info.setText(tr("{d} · Remote ID: {r} · Device no. {s}, firmware {v}")
                          .format(d=dt(rec.time), r=remote_label(rec), s=serial, v=rec.version))
        text, ok = wiremap_status(rec)
        faults = fault_summary(rec)
        col = tc({True: "ok", False: "bad", None: "neutral"}[ok])
        rcol = tc(result_kind(rec.result))
        self.status.setText(f"<b>{tr("Result:")}</b> <span style='color:{rcol}'><b>{tr(rec.result)}</b></span>"
                            f" &nbsp;·&nbsp; <b>{tr("Wiremap:")}</b> <span style='color:{col}'><b>{text}</b></span>"
                            + (f"<br><span style='color:{tc("bad")}'>{"; ".join(faults)}</span>" if faults else ""))
        tests = rec.autotests
        self.tests.setRowCount(len(tests))
        for i, t in enumerate(tests):
            vals = [tr(t["name"]), tr("Qualified") if t["qualified"] else tr("Disqualified"),
                    reason_text(t["reason"])]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if c:
                    it.setForeground(QColor(tc("ok" if t["qualified"] else "bad")))
                it.setToolTip(v)
                self.tests.setItem(i, c, it)
        self.tests.setWordWrap(True)
        self.tests.resizeColumnsToContents()
        self.tests.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.tests.resizeRowsToContents()
        for i in range(4):
            vals = [tr("Pair {p}").format(p=PAIRS[i]), nf(rec.lengths[i], 1), nf(rec.delays_ns[i], 3)]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if c:
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.lengths.setItem(i, c, it)
        for i, w in enumerate(rec.wires):
            for c, v in enumerate([w["name"], wire_text(w), tr("Error") if w["fault"] else tr("OK")]):
                it = QTableWidgetItem(v)
                if c == 2:
                    it.setForeground(QColor(tc("bad" if w["fault"] else "ok")))
                self.wires.setItem(i, c, it)
        self.wires.resizeRowsToContents()


class MainWindow(QMainWindow):
    TITLE = "CableIQ Client"

    def __init__(self, pcap=None, source=""):
        super().__init__()
        self.cfg = load_config()
        i18n.set_lang(LANG_OVERRIDE or self.cfg["lang"])
        install_qt_translators(i18n.lang())
        self.apply_scheme()
        self.source = source
        self.update_title()
        self.resize(1450, 820)
        self.pcap = pcap
        self.serial, self.recs = "", []
        self.thread = None
        self.cols = [tr("Cable ID"), tr("Date/time"), tr("Length (m)"), tr("Result"), tr("Qualified"),
                     tr("Wiremap")]

        # toolbar
        tb = QToolBar()
        tb.setMovable(False)
        self.addToolBar(tb)
        self.act_read = QAction(tr("Read from device"), self, triggered=self.read_device)
        tb.addAction(self.act_read)
        self.act_save = QAction(tr("Save measurement set…"), self, triggered=self.save_set)
        self.act_load = QAction(tr("Load measurement set…"), self, triggered=self.load_set)
        tb.addAction(self.act_load)
        tb.addAction(self.act_save)
        tb.addSeparator()
        self.btn_pdf = QToolButton()
        self.btn_pdf.setText(tr("PDF test report"))
        self.btn_pdf.setPopupMode(QToolButton.InstantPopup)
        m = QMenu(self.btn_pdf)
        self.act_pdf_sel = m.addAction(tr("Export selected measurements…"), lambda: self.export(selected=True))
        self.act_pdf_all = m.addAction(tr("Export all measurements…"), lambda: self.export(selected=False))
        self.btn_pdf.setMenu(m)
        tb.addWidget(self.btn_pdf)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(spacer)
        self.btn_settings = QToolButton()
        self.btn_settings.setText(tr("Settings"))
        self.btn_settings.setPopupMode(QToolButton.InstantPopup)
        self.btn_settings.setMenu(self.build_settings_menu())
        tb.addWidget(self.btn_settings)

        # list
        self.table = QTableWidget(0, len(self.cols))
        self.table.setHorizontalHeaderLabels(self.cols)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self.on_selection)

        # report details
        box = QGroupBox(tr("Report details"))
        form = QFormLayout(box)
        self.ed_loc = QLineEdit(self.cfg["location"])
        self.ed_loc.setPlaceholderText(tr("e.g. Building B10, server room"))
        self.ed_tester = QLineEdit(self.cfg["tester"])
        self.ed_tester.setPlaceholderText(tr("Default if the device has no entry"))
        form.addRow(tr("Location:"), self.ed_loc)
        form.addRow(tr("Tested by (default):"), self.ed_tester)
        self.logo_prev = QLabel()
        self.logo_prev.setFixedHeight(48)
        self.logo_prev.setMinimumWidth(120)
        self.logo_prev.setStyleSheet("border: 1px solid #888; background: white; color: #444;")
        self.logo_prev.setAlignment(Qt.AlignCenter)
        b_logo = QPushButton(tr("Choose logo…"), clicked=self.choose_logo)
        b_clear = QPushButton(tr("Remove"), clicked=self.clear_logo)
        row = QHBoxLayout()
        row.addWidget(self.logo_prev, 1)
        row.addWidget(b_logo)
        row.addWidget(b_clear)
        form.addRow(tr("Logo:"), row)
        self.cb_sign = QCheckBox(tr("Add signature field (place, date, signature)"))
        self.cb_sign.setChecked(self.cfg["signature"])
        self.cb_sign.toggled.connect(self.store_fields)
        form.addRow(tr("Signature field in PDF:"), self.cb_sign)
        self.ed_loc.editingFinished.connect(self.store_fields)
        self.ed_tester.editingFinished.connect(self.store_fields)
        self.show_logo()

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(self.table, 1)
        ll.addWidget(box)
        self.detail = Detail()
        self.cur_rec = None
        self.detail.operators_changed.connect(self.on_ops_changed)
        self.detail.operators_reset.connect(self.on_ops_reset)
        self.detail.note_edited.connect(self.on_note_edited)
        self.detail.note_done.connect(lambda: save_config(self.cfg))
        split = QSplitter()
        split.addWidget(left)
        split.addWidget(self.detail)
        split.setStretchFactor(0, 6)
        split.setStretchFactor(1, 5)
        self.setCentralWidget(split)

        self.progress = QProgressBar()
        self.progress.setMaximumWidth(220)
        self.progress.hide()
        self.statusBar().addPermanentWidget(self.progress)
        QGuiApplication.styleHints().colorSchemeChanged.connect(self.on_scheme_changed)
        self.update_actions()

    # --- settings: language and appearance --------------------------------
    def build_settings_menu(self):
        menu = QMenu(self)
        lm = menu.addMenu(tr("Language"))
        g1 = QActionGroup(self)
        for code, label in (("auto", tr("Automatic")), ("de", LANGS["de"]), ("en", LANGS["en"])):
            a = lm.addAction(label)
            a.setCheckable(True)
            a.setChecked(self.cfg["lang"] == code)
            a.triggered.connect(lambda _=False, c=code: self.set_language(c))
            g1.addAction(a)
        tm = menu.addMenu(tr("Appearance"))
        g2 = QActionGroup(self)
        for code, label in (("auto", tr("Automatic (system)")), ("light", tr("Light")), ("dark", tr("Dark"))):
            a = tm.addAction(label)
            a.setCheckable(True)
            a.setChecked(self.cfg["theme"] == code)
            a.triggered.connect(lambda _=False, c=code: self.set_theme(c))
            g2.addAction(a)
        menu.addSeparator()
        quit_act = menu.addAction(tr("Quit"), self.close)
        quit_act.setShortcut(QKeySequence.Quit)
        return menu

    def apply_scheme(self):
        apply_theme(self.cfg["theme"])

    def set_theme(self, code):
        self.cfg["theme"] = code
        save_config(self.cfg)
        self.apply_scheme()
        self.rerender()

    def on_scheme_changed(self, *_):
        self.rerender()

    def rerender(self):
        """Rebuild the color-dependent parts (list colors, details, wiremap)."""
        rows = self.selected_rows()
        cur = self.table.currentRow()
        self.fill_table()
        self.table.clearSelection()
        for r in rows:
            self.table.selectRow(r)
        if 0 <= cur < len(self.recs):
            self.table.setCurrentCell(cur, 0)
        self.refresh_detail()
        self.detail.wiremap.update()

    def set_language(self, code):
        if self.thread:
            self.statusBar().showMessage(tr("The language cannot be changed while reading."), 5000)
            self.btn_settings.setMenu(self.build_settings_menu())
            return
        self.store_fields()
        self.cfg["lang"] = code
        save_config(self.cfg)
        self.rebuild()

    def rebuild(self):
        """Rebuild the window in the new language and carry the state over."""
        new = MainWindow(self.pcap, self.source)
        new.serial, new.recs = self.serial, self.recs
        new.resize(self.size())
        new.fill_table()
        cur = self.table.currentRow()
        if 0 <= cur < len(self.recs):
            new.table.selectRow(cur)
        _WINDOWS.append(new)
        new.show()
        QGuiApplication.styleHints().colorSchemeChanged.disconnect(self.on_scheme_changed)
        self.close()
        if self in _WINDOWS:
            _WINDOWS.remove(self)

    def update_title(self):
        self.setWindowTitle(f"{self.TITLE} – {self.source}" if self.source else self.TITLE)

    # --- report details --------------------------------------------------
    def store_fields(self):
        self.cfg["location"] = self.ed_loc.text().strip()
        self.cfg["tester"] = self.ed_tester.text().strip()
        self.cfg["signature"] = self.cb_sign.isChecked()
        save_config(self.cfg)

    def show_logo(self):
        path = self.cfg.get("logo", "")
        pm = QPixmap(path) if path else QPixmap()
        if pm.isNull():
            self.logo_prev.setPixmap(QPixmap())
            self.logo_prev.setText(tr("no logo") if not path else tr("File not readable"))
        else:
            self.logo_prev.setText("")
            self.logo_prev.setPixmap(pm.scaledToHeight(44, Qt.SmoothTransformation))
        self.logo_prev.setToolTip(path)

    def choose_logo(self):
        start = str(Path(self.cfg["logo"]).parent) if self.cfg["logo"] else str(Path.home())
        path, _ = QFileDialog.getOpenFileName(self, tr("Choose logo"), start,
                                              tr("Images") + " (*.png *.jpg *.jpeg *.bmp *.gif *.svg)")
        if path:
            if QPixmap(path).isNull():
                QMessageBox.warning(self, tr("Logo"), tr("The file could not be read as an image."))
                return
            self.cfg["logo"] = path
            save_config(self.cfg)
            self.show_logo()

    def clear_logo(self):
        self.cfg["logo"] = ""
        save_config(self.cfg)
        self.show_logo()

    # --- reading -------------------------------------------------------
    def read_device(self):
        if self.thread:
            return
        self.act_read.setEnabled(False)
        self.act_load.setEnabled(False)
        self.statusBar().showMessage(tr("Reading measurements …") if not self.pcap
                                     else tr("Loading {f} …").format(f=self.pcap))
        self.progress.setRange(0, 0)
        self.progress.show()
        self.thread = QThread()
        self.worker = ReadWorker(self.pcap)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.on_progress)
        self.worker.done.connect(self.on_done)
        self.worker.failed.connect(self.on_failed)
        for sig in (self.worker.done, self.worker.failed):
            sig.connect(self.thread.quit)
        self.thread.finished.connect(self.on_thread_finished)
        self.thread.start()

    def on_progress(self, n, total):
        self.progress.setRange(0, max(total, 1))
        self.progress.setValue(n)
        self.statusBar().showMessage(tr("Reading measurement {n} of {t} …").format(n=n, t=total))

    def on_done(self, serial, recs):
        self.serial, self.recs = serial, recs
        self.source = ""
        self.update_title()
        self.fill_table()
        self.statusBar().showMessage(tr("{n} measurements read from device {s}").format(n=len(recs), s=serial), 8000)

    def on_failed(self, msg):
        self.statusBar().clearMessage()
        QMessageBox.critical(self, tr("Reading failed"), msg)

    def on_thread_finished(self):
        self.thread.deleteLater()
        self.thread = None
        self.progress.hide()
        self.act_read.setEnabled(True)
        self.act_load.setEnabled(True)

    def fill_table(self):
        self.table.setRowCount(len(self.recs))
        for i, r in enumerate(self.recs):
            text, ok = wiremap_status(r)
            cells = [r.name, dt(r.time), nf(max(r.lengths), 1),  # length = longest single value of the four pairs
                     tr(r.result), "; ".join(tr(n) for n in r.qualified_names), text]
            for c, v in enumerate(cells):
                it = QTableWidgetItem(v)
                it.setToolTip(v)
                if c == 2:
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if c == 3:
                    it.setForeground(QColor(tc(result_kind(r.result))))
                if c == 5:
                    it.setForeground(QColor(tc({True: "ok", False: "bad", None: "neutral"}[ok])))
                self.table.setItem(i, c, it)
        self.table.horizontalHeaderItem(2).setToolTip(tr("Longest value of the four wire pairs"))
        for c in (1, 2, 3, 5):
            self.table.resizeColumnToContents(c)
        if self.recs:
            self.table.selectRow(0)
        else:
            self.cur_rec = None
            self.refresh_detail()
        self.update_actions()

    # --- selection and export ------------------------------------------
    def selected_rows(self):
        return sorted({i.row() for i in self.table.selectedIndexes()})

    def on_selection(self):
        rows = self.selected_rows()
        cur = self.table.currentRow()
        if cur not in rows and rows:
            cur = rows[0]
        self.cur_rec = self.recs[cur] if 0 <= cur < len(self.recs) else None
        self.refresh_detail()
        self.update_actions()

    # --- "Tested by" per measurement ------------------------------------
    def op_key(self, rec):
        return f"{self.serial}:{rec.ts}:{rec.name}"

    def ops_for(self, rec):
        """(lines, changed): the stored change or the value from the device."""
        ov = self.cfg["operators"].get(self.op_key(rec))
        return (list(ov), True) if ov is not None else (rec.operator_lines, False)

    def refresh_detail(self):
        rec = self.cur_rec
        ops, changed = self.ops_for(rec) if rec else (None, False)
        self.detail.show_record(rec, self.serial, ops, changed, self.cfg["notes"].get(self.op_key(rec), "") if rec else "")

    def on_note_edited(self, text):
        if self.cur_rec is None:
            return
        if text.strip():
            self.cfg["notes"][self.op_key(self.cur_rec)] = text
        else:
            self.cfg["notes"].pop(self.op_key(self.cur_rec), None)

    def on_ops_changed(self, lines):
        rec = self.cur_rec
        if rec is None:
            return
        lines = (lines + ["", ""])[:2]
        if lines == rec.operator_lines:
            self.cfg["operators"].pop(self.op_key(rec), None)
        else:
            self.cfg["operators"][self.op_key(rec)] = lines
        save_config(self.cfg)
        self.refresh_detail()

    def on_ops_reset(self):
        if self.cur_rec is not None:
            self.cfg["operators"].pop(self.op_key(self.cur_rec), None)
            save_config(self.cfg)
            self.refresh_detail()

    # --- save/load a measurement set -------------------------------------
    def save_set(self):
        if not self.recs:
            return
        self.store_fields()
        start = Path(self.cfg["set_dir"] or Path.home())
        name = tr("cableiq-measurements-{s}-{d}.json").format(s=self.serial,
                                                           d=f"{datetime.datetime.now():%Y%m%d-%H%M}")
        path, _ = QFileDialog.getSaveFileName(self, tr("Save measurement set"), str(start / name),
                                              tr("CableIQ measurement set") + " (*.json)")
        if not path:
            return
        if not path.lower().endswith(".json"):
            path += ".json"
        ops = [self.cfg["operators"].get(self.op_key(r)) for r in self.recs]
        notes = [self.cfg["notes"].get(self.op_key(r)) for r in self.recs]
        try:
            cableiq_store.save_set(path, self.serial, self.recs, ops,
                                   {"location": self.cfg["location"], "tester": self.cfg["tester"]},
                                   self.cfg["logo"], notes)
        except cableiq_store.StoreError as e:
            QMessageBox.critical(self, tr("Save measurement set"), str(e))
            return
        self.cfg["set_dir"] = str(Path(path).parent)
        save_config(self.cfg)
        self.statusBar().showMessage(tr("{n} measurements saved to {f}").format(n=len(self.recs), f=path), 10000)

    def load_set(self, path=None, ask_protocol=True):
        if self.thread:
            return
        if not path:
            start = self.cfg["set_dir"] or str(Path.home())
            path, _ = QFileDialog.getOpenFileName(self, tr("Load measurement set"), start,
                                                  tr("CableIQ measurement set") + " (*.json)")
            if not path:
                return
        try:
            s = cableiq_store.load_set(path)
        except cableiq_store.StoreError as e:
            QMessageBox.critical(self, tr("Load measurement set"), str(e))
            return
        self.serial, self.recs = s["serial"], s["recs"]
        for r, o in zip(self.recs, s["ops"]):  # restore changed "Tested by" lines
            key = self.op_key(r)
            if o is not None and o != r.operator_lines:
                self.cfg["operators"][key] = o
            else:
                self.cfg["operators"].pop(key, None)
        for r, n in zip(self.recs, s["notes"]):  # restore notes
            if n:
                self.cfg["notes"][self.op_key(r)] = n
        self.cfg["set_dir"] = str(Path(path).parent)
        save_config(self.cfg)
        self.fill_table()
        self.source = Path(path).name
        self.update_title()
        if ask_protocol:
            self.apply_protocol(s)
        msg = tr("{n} measurements loaded from {f}").format(n=len(self.recs), f=Path(path).name)
        if s["saved"]:
            msg += " " + tr("(saved {d})").format(d=s["saved"].replace("T", " "))
        self.statusBar().showMessage(msg, 10000)

    def apply_protocol(self, s):
        """Adopt the report details from the measurement set after asking."""
        p, logo = s["protocol"], s["logo"]
        new = {"location": p.get("location", self.cfg["location"]), "tester": p.get("tester", self.cfg["tester"])}
        if not (p or logo) or (new["location"] == self.cfg["location"] and new["tester"] == self.cfg["tester"]
                               and not logo):
            return
        lines = [tr("Location:") + f" {p.get("location") or "–"}",
                 tr("Tested by (default):") + f" {p.get("tester") or "–"}"]
        if logo:
            lines.append(tr("Logo:") + f" {logo[0]}")
        r = QMessageBox.question(self, tr("Report details"),
                                 tr("The measurement set contains report details:") + "\n\n" + "\n".join(lines)
                                 + "\n\n" + tr("Replace the current details?"),
                                 QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if r != QMessageBox.Yes:
            return
        self.ed_loc.setText(new["location"])
        self.ed_tester.setText(new["tester"])
        if logo:
            try:
                CONFIG.parent.mkdir(parents=True, exist_ok=True)
                target = CONFIG.parent / f"logo-{logo[0]}"
                target.write_bytes(logo[1])
                self.cfg["logo"] = str(target)
            except OSError as e:
                QMessageBox.warning(self, tr("Logo"), tr("The logo could not be saved: {e}").format(e=e))
        self.store_fields()
        self.show_logo()

    def update_actions(self):
        self.act_pdf_sel.setEnabled(bool(self.selected_rows()))
        self.act_pdf_all.setEnabled(bool(self.recs))
        self.btn_pdf.setEnabled(bool(self.recs))
        self.act_save.setEnabled(bool(self.recs))

    def export(self, selected):
        self.store_fields()
        rows = self.selected_rows() if selected else list(range(len(self.recs)))
        if not rows:
            return
        recs = [self.recs[i] for i in rows]
        start = Path(self.cfg["pdf_dir"] or Path.home())
        name = recs[0].name.strip(" #").replace("/", "_") if len(recs) == 1 else tr("Test report")
        path, _ = QFileDialog.getSaveFileName(self, tr("Save PDF test report"), str(start / f"{name}.pdf"),
                                              "PDF (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        logo = self.cfg["logo"]
        if logo and QPixmap(logo).isNull():
            QMessageBox.warning(self, tr("Logo"),
                                tr("The logo {f} is not readable and will be omitted.").format(f=logo))
            logo = ""
        try:
            people = [" · ".join(t for t in self.ops_for(r)[0] if t) for r in recs]
            notes = [self.cfg["notes"].get(self.op_key(r), "") for r in recs]
            export_pdf(path, recs, self.serial, self.cfg["location"], self.cfg["tester"], logo, people, notes,
                       self.cfg["signature"])
        except OSError as e:
            QMessageBox.critical(self, tr("Export"), tr("The PDF could not be written:") + f"\n{e}")
            return
        self.cfg["pdf_dir"] = str(Path(path).parent)
        save_config(self.cfg)
        self.statusBar().showMessage(tr("{n} measurement(s) exported to {f}").format(n=len(recs), f=path), 10000)

    def closeEvent(self, ev):
        self.store_fields()
        if self.thread:
            self.thread.quit()
            self.thread.wait(3000)
        super().closeEvent(ev)


def main():
    global LANG_OVERRIDE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pcap", help="load from a usbmon capture instead of the device")
    ap.add_argument("--set", help="load a saved measurement set instead of reading the device")
    ap.add_argument("--lang", choices=["auto", "de", "en"], help="language (default: from the environment)")
    ap.add_argument("--no-auto", action="store_true", help="do not read from the device at start")
    a = ap.parse_args()
    LANG_OVERRIDE = a.lang
    app = QApplication(sys.argv)
    app.setApplicationName("cableiq")
    # Ctrl+C in the terminal: close the windows normally (saves the configuration). The timer gives the
    # Python interpreter regular chances to run the signal handler while Qt is running.
    signal.signal(signal.SIGINT, lambda *_: QApplication.closeAllWindows())
    wake = QTimer()
    wake.start(250)
    wake.timeout.connect(lambda: None)
    w = MainWindow(a.pcap)
    _WINDOWS.append(w)
    w.show()
    if a.set:
        w.load_set(a.set, ask_protocol=False)
    elif not a.no_auto:
        w.read_device()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
